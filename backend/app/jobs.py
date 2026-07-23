# 합성·익스포트 작업 큐 — GPU 가 1장이라 워커 스레드도 1개다

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field

from . import store, synth

log = logging.getLogger("voicerecorder.jobs")


@dataclass
class _Task:
    job_id: str
    project_id: str
    kind: str  # synthesize | export
    scene_ids: list[str] = field(default_factory=list)


class JobRunner:
    """작업을 순서대로 하나씩 처리한다.

    Celery/Redis 를 붙이지 않은 이유: GPU 가 1장이라 동시 실행이 전체 시간을 줄여주지
    않고, HEAXHub 는 앱을 SIF 하나로 띄우므로 외부 브로커를 요구하면 배포가 복잡해진다.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[_Task | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        # 이전 프로세스가 남긴 미완 작업은 살릴 방법이 없으니 실패로 닫는다.
        self._fail_orphans()
        self._thread = threading.Thread(target=self._loop, name="voicerec-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._queue.put(None)
        self._thread.join(timeout=5)
        self._thread = None

    # ── 제출 ────────────────────────────────────────────────────────────────

    def submit_synthesis(self, project_id: str, scene_ids: list[str]) -> str:
        job_id = store.create_job(project_id, "synthesize", len(scene_ids))
        self._queue.put(_Task(job_id, project_id, "synthesize", scene_ids))
        return job_id

    def submit_export(self, project_id: str) -> str:
        job_id = store.create_job(project_id, "export", 1)
        self._queue.put(_Task(job_id, project_id, "export"))
        return job_id

    # ── 실행 ────────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                return
            try:
                self._run(task)
            except Exception as exc:  # noqa: BLE001 - 워커는 어떤 실패에도 죽으면 안 된다
                log.exception("작업 실패: %s", task.job_id)
                store.update_job(task.job_id, status="error", error=str(exc)[:500])
            finally:
                self._queue.task_done()

    def _run(self, task: _Task) -> None:
        store.update_job(task.job_id, status="running", done=0)
        project = store.get_project(task.project_id)
        if project is None:
            store.update_job(task.job_id, status="error", error="프로젝트가 없습니다")
            return

        if task.kind == "synthesize":
            self._run_synthesis(task, project)
        elif task.kind == "export":
            self._run_export(task, project)
        else:
            store.update_job(task.job_id, status="error", error=f"알 수 없는 작업: {task.kind}")

    def _run_synthesis(self, task: _Task, project: dict) -> None:
        failures: list[str] = []
        for done, scene_id in enumerate(task.scene_ids):
            scene = store.get_scene(scene_id)
            if scene is None:
                continue
            label = scene.get("title") or (scene["text"][:24] + "…")
            store.update_job(task.job_id, current=f"{scene['position'] + 1}. {label}", done=done)
            try:
                synth.synthesize_scene(project, scene)
            except Exception as exc:  # noqa: BLE001 - 한 씬이 실패해도 나머지는 계속한다
                log.warning("씬 합성 실패 %s: %s", scene_id, exc)
                failures.append(f"{scene['position'] + 1}번: {exc}")

        store.touch_project(project["id"])
        store.update_job(
            task.job_id,
            status="error" if len(failures) == len(task.scene_ids) and failures else "done",
            done=len(task.scene_ids),
            current=None,
            error="\n".join(failures)[:1000] if failures else None,
            result={"failed": len(failures), "total": len(task.scene_ids)},
        )

    def _run_export(self, task: _Task, project: dict) -> None:
        def progress(done: int, total: int) -> None:
            store.update_job(task.job_id, done=done, total=total, current=f"{done}/{total} 씬 병합")

        result = synth.export_project(project, progress=progress)
        store.update_job(task.job_id, status="done", current=None, result=result)

    def _fail_orphans(self) -> None:
        with store.write() as conn:
            conn.execute(
                """
                UPDATE jobs SET status = 'error', error = '서버 재시작으로 중단됨'
                 WHERE status IN ('queued', 'running')
                """
            )


runner = JobRunner()
