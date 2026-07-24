"""VoiceRecorder 백엔드 — 내레이션 스크립트를 씬 단위 음성(mp3)으로 만든다.

HEAXHub fastapi_react 스택 규약을 따른다:
  - /api/* 라우트를 **먼저** 선언하고, 그 뒤에 frontend/dist 를 StaticFiles 로 "/" 에 마운트한다.
    FastAPI 는 등록 순서대로 매칭하므로 순서가 뒤집히면 API 가 전부 SPA 로 먹힌다.
  - Caddy 가 /apps/<slug>/ 를 base path 로 프록시하므로 uvicorn 은 --root-path $ROOT_PATH 를
    받는다. 프런트는 상대경로로만 fetch 하고 Vite 는 base:"./" 로 빌드해 서브경로에서도 깨지지 않는다.
"""

from __future__ import annotations

import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import config, store, synth
from .jobs import runner
from .models import (
    ApplySpeedRequest,
    DictionaryEntryIn,
    FitTimecodeRequest,
    ParseRequest,
    ParseResponse,
    ProjectCreate,
    ProjectPatch,
    ReorderRequest,
    SceneCreate,
    ScenePatch,
    ScriptReplace,
    SynthesizeRequest,
)
from .script_parser import parse_script
from .timeline import render_srt
from .tts import describe_engines

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("voicerecorder")


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.ensure_dirs()
    store.init_db()
    runner.start()
    yield
    runner.stop()


app = FastAPI(
    title="VoiceRecorder",
    description="내레이션 스크립트를 씬 단위 음성(mp3)으로 만드는 HEAXHub 서브 플랫폼",
    version="0.1.0",
    lifespan=lifespan,
)


# ── 공통 ────────────────────────────────────────────────────────────────────


def _project_or_404(project_id: str) -> dict:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다")
    return project


def _scene_or_404(project_id: str, scene_id: str) -> dict:
    scene = store.get_scene(scene_id)
    if scene is None or scene["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="씬을 찾을 수 없습니다")
    return scene


def _project_payload(project: dict) -> dict:
    timeline, views = synth.project_timeline(project)
    drift_by_id = {e.scene_id: e for e in timeline.entries}
    scenes = []
    for view in views:
        entry = drift_by_id.get(view["id"])
        scenes.append(
            {
                **view,
                "start_sec": round(entry.speech_start_sec, 3) if entry else None,
                "end_sec": round(entry.speech_end_sec, 3) if entry else None,
                "drift_sec": round(entry.drift_sec, 3) if entry and entry.drift_sec is not None else None,
            }
        )
    return {
        "project": {**project, "read_numbers": bool(project["read_numbers"])},
        "scenes": scenes,
        "total_sec": round(timeline.total_sec, 3),
        "ready_count": sum(1 for s in scenes if s["status"] == "ready"),
        "job": store.latest_job(project["id"]),
    }


# ── 상태 ────────────────────────────────────────────────────────────────────


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/engines")
def engines() -> dict:
    return {"engines": describe_engines(), "default": config.DEFAULT_ENGINE}


# ── 스크립트 파싱 ───────────────────────────────────────────────────────────


@app.post("/api/scripts/parse", response_model=ParseResponse)
def parse(payload: ParseRequest) -> ParseResponse:
    result = parse_script(payload.raw_script)
    return ParseResponse(
        structured=result.structured,
        scenes=[
            {
                "index": s.index,
                "text": s.text,
                "number": s.number,
                "title": s.title,
                "target_start_sec": s.target_start_sec,
                "target_end_sec": s.target_end_sec,
                "target_duration_sec": s.target_duration_sec,
                "char_count": len(s.text),
            }
            for s in result.scenes
        ],
    )


# ── 프로젝트 ────────────────────────────────────────────────────────────────


@app.get("/api/projects")
def list_projects() -> dict:
    return {"projects": store.list_projects()}


@app.post("/api/projects", status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate) -> dict:
    parsed = parse_script(payload.raw_script)
    if not parsed.scenes:
        raise HTTPException(status_code=400, detail="스크립트에서 씬을 찾지 못했습니다")

    title = payload.title.strip() or (parsed.scenes[0].title or parsed.scenes[0].text[:30])
    project_id = store.create_project(**{**payload.model_dump(), "title": title})
    store.replace_scenes(
        project_id,
        [
            {
                "number": s.number,
                "title": s.title,
                "text": s.text,
                "target_start_sec": s.target_start_sec,
                "target_end_sec": s.target_end_sec,
            }
            for s in parsed.scenes
        ],
    )
    return _project_payload(_project_or_404(project_id))


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict:
    return _project_payload(_project_or_404(project_id))


@app.patch("/api/projects/{project_id}")
def patch_project(project_id: str, payload: ProjectPatch) -> dict:
    project = _project_or_404(project_id)
    store.update_project(project_id, payload.model_dump(exclude_unset=True))
    updated = _project_or_404(project_id)
    # 속도만 바뀌었으면 모델을 다시 돌리지 않고 ffmpeg 로 다시 렌더링한다.
    if payload.speed is not None and payload.speed != project["speed"]:
        _rerender_all(updated)
    return _project_payload(_project_or_404(project_id))


@app.put("/api/projects/{project_id}/script")
def replace_script(project_id: str, payload: ScriptReplace) -> dict:
    project = _project_or_404(project_id)
    parsed = parse_script(payload.raw_script)
    if not parsed.scenes:
        raise HTTPException(status_code=400, detail="스크립트에서 씬을 찾지 못했습니다")

    # 씬 id 가 바뀌므로 기존 오디오는 버린다 (남겨두면 고아 파일이 쌓인다)
    shutil.rmtree(config.project_dir(project_id) / "raw", ignore_errors=True)
    shutil.rmtree(config.project_dir(project_id) / "scenes", ignore_errors=True)

    store.update_project(project_id, {"raw_script": payload.raw_script})
    store.replace_scenes(
        project_id,
        [
            {
                "number": s.number,
                "title": s.title,
                "text": s.text,
                "target_start_sec": s.target_start_sec,
                "target_end_sec": s.target_end_sec,
            }
            for s in parsed.scenes
        ],
    )
    return _project_payload(_project_or_404(project["id"]))


@app.delete("/api/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str) -> None:
    _project_or_404(project_id)
    shutil.rmtree(config.project_dir(project_id), ignore_errors=True)
    store.delete_project(project_id)


# ── 씬 ──────────────────────────────────────────────────────────────────────


@app.post("/api/projects/{project_id}/scenes", status_code=status.HTTP_201_CREATED)
def create_scene(project_id: str, payload: SceneCreate) -> dict:
    project = _project_or_404(project_id)
    order = [s["id"] for s in store.list_scenes(project_id)]

    insert_at = len(order)
    if payload.after_scene_id and payload.after_scene_id in order:
        insert_at = order.index(payload.after_scene_id) + 1

    # 일단 맨 뒤에 넣고, 원하는 자리로 옮긴 순서를 통째로 다시 매긴다.
    new_id = store.insert_scene(project_id, len(order), text=payload.text, title=payload.title)
    order.insert(insert_at, new_id)
    store.reorder_scenes(project_id, order)
    return _project_payload(project)


@app.patch("/api/projects/{project_id}/scenes/{scene_id}")
def patch_scene(project_id: str, scene_id: str, payload: ScenePatch) -> dict:
    project = _project_or_404(project_id)
    scene = _scene_or_404(project_id, scene_id)

    patch = payload.model_dump(exclude_unset=True, exclude={"reset"})
    for field in payload.reset or []:
        patch[field] = None

    speed_changed = "speed" in patch and patch["speed"] != scene.get("speed")
    text_changed = "text" in patch and patch["text"] != scene["text"]

    store.update_scene(scene_id, patch)
    store.touch_project(project_id)

    updated = _scene_or_404(project_id, scene_id)
    # 텍스트가 그대로면 모델을 다시 돌릴 필요가 없다 — ffmpeg 로 속도만 다시 입힌다.
    if speed_changed and not text_changed:
        try:
            synth.rerender_speed(project, updated)
        except Exception as exc:  # noqa: BLE001
            log.warning("속도 재렌더 실패 %s: %s", scene_id, exc)
    return _project_payload(project)


@app.delete("/api/projects/{project_id}/scenes/{scene_id}")
def delete_scene(project_id: str, scene_id: str) -> dict:
    project = _project_or_404(project_id)
    _scene_or_404(project_id, scene_id)
    config.scene_raw_path(project_id, scene_id).unlink(missing_ok=True)
    config.scene_audio_path(project_id, scene_id).unlink(missing_ok=True)
    store.delete_scene(scene_id)
    store.compact_positions(project_id)
    return _project_payload(project)


@app.post("/api/projects/{project_id}/scenes/reorder")
def reorder(project_id: str, payload: ReorderRequest) -> dict:
    project = _project_or_404(project_id)
    known = {s["id"] for s in store.list_scenes(project_id)}
    if set(payload.scene_ids) != known:
        raise HTTPException(status_code=400, detail="씬 목록이 현재 상태와 다릅니다")
    store.reorder_scenes(project_id, payload.scene_ids)
    return _project_payload(project)


@app.post("/api/projects/{project_id}/apply-speed")
def apply_speed(project_id: str, payload: ApplySpeedRequest) -> dict:
    """전 씬 속도를 한 값으로 통일한다 — 프로젝트 기본 속도를 바꾸고 씬별 override 를 지운다.

    상단 슬라이더(프로젝트 기본값)만으로는 씬에 개별 속도가 걸린 경우 그 씬이 안 따라온다.
    이 액션은 그 override 까지 제거해 정말로 전부 통일한다. 텍스트는 그대로라 모델을
    다시 돌리지 않고 원본 wav 를 ffmpeg 로 다시 렌더링만 한다.
    """
    project = _project_or_404(project_id)
    store.update_project(project_id, {"speed": payload.speed})
    for scene in store.list_scenes(project_id):
        if scene.get("speed") is not None:
            store.update_scene(scene["id"], {"speed": None})
    updated = _project_or_404(project_id)
    _rerender_all(updated)
    return _project_payload(updated)


@app.post("/api/projects/{project_id}/fit-timecode")
def fit_timecode(project_id: str, payload: FitTimecodeRequest) -> dict:
    """전 씬을 스크립트 타임코드에 자동으로 맞춘다 (짧으면 무음, 넘치면 배속)."""
    project = _project_or_404(project_id)
    scenes = store.list_scenes(project_id)
    if not scenes:
        raise HTTPException(status_code=400, detail="씬이 없습니다")
    if any(synth.scene_status(project, s) != "ready" for s in scenes):
        raise HTTPException(status_code=400, detail="먼저 모든 씬의 음성을 생성하세요")
    if not any(synth._target_duration(s) for s in scenes):
        raise HTTPException(status_code=400, detail="타임코드가 없어 맞출 수 없습니다")

    report = synth.fit_to_timecode(project, max_speed=payload.max_speed)
    result = _project_payload(_project_or_404(project_id))
    result["fit_report"] = report
    return result


@app.get("/api/projects/{project_id}/scenes/{scene_id}/audio")
def scene_audio(project_id: str, scene_id: str):
    _project_or_404(project_id)
    _scene_or_404(project_id, scene_id)
    path = config.scene_audio_path(project_id, scene_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="아직 합성되지 않았습니다")
    return FileResponse(path, media_type="audio/wav", filename=f"{scene_id}.wav")


# ── 합성 · 익스포트 ─────────────────────────────────────────────────────────


@app.post("/api/projects/{project_id}/synthesize", status_code=status.HTTP_202_ACCEPTED)
def synthesize(project_id: str, payload: SynthesizeRequest) -> dict:
    project = _project_or_404(project_id)
    scenes = store.list_scenes(project_id)

    if payload.scene_ids:
        wanted = set(payload.scene_ids)
        targets = [s for s in scenes if s["id"] in wanted]
    elif payload.force:
        targets = scenes
    else:
        targets = [s for s in scenes if synth.scene_status(project, s) != "ready"]

    if not targets:
        raise HTTPException(status_code=400, detail="합성할 씬이 없습니다 (모두 최신 상태)")

    job_id = runner.submit_synthesis(project_id, [s["id"] for s in targets])
    return {"job_id": job_id, "scene_count": len(targets)}


@app.post("/api/projects/{project_id}/export", status_code=status.HTTP_202_ACCEPTED)
def export(project_id: str) -> dict:
    project = _project_or_404(project_id)
    ready = [s for s in store.list_scenes(project_id) if synth.scene_status(project, s) == "ready"]
    if not ready:
        raise HTTPException(status_code=400, detail="합성된 씬이 없습니다")
    return {"job_id": runner.submit_export(project_id)}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    return job


@app.get("/api/projects/{project_id}/export/audio")
def download_mp3(project_id: str):
    project = _project_or_404(project_id)
    path = config.export_mp3_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="아직 내보내지 않았습니다")
    return FileResponse(path, media_type="audio/mpeg", filename=f"{_safe_name(project)}.mp3")


@app.get("/api/projects/{project_id}/export/srt")
def download_srt(project_id: str):
    project = _project_or_404(project_id)
    path = config.export_srt_path(project_id)
    if not path.exists():
        # 익스포트를 안 했어도 준비된 씬만으로 자막은 즉시 만들 수 있다
        timeline, _ = synth.project_timeline(project)
        if not timeline.entries:
            raise HTTPException(status_code=404, detail="합성된 씬이 없습니다")
        return PlainTextResponse(
            render_srt(timeline),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{_safe_name(project)}.srt"'},
        )
    return FileResponse(path, media_type="text/plain", filename=f"{_safe_name(project)}.srt")


def _safe_name(project: dict) -> str:
    name = "".join(c for c in project["title"] if c.isalnum() or c in " _-").strip()
    return (name or "narration")[:60]


def _rerender_all(project: dict) -> None:
    for scene in store.list_scenes(project["id"]):
        try:
            synth.rerender_speed(project, scene)
        except Exception as exc:  # noqa: BLE001
            log.warning("속도 재렌더 실패 %s: %s", scene["id"], exc)


# ── 보이스 프로필 ───────────────────────────────────────────────────────────


@app.get("/api/voices")
def list_voices() -> dict:
    return {"voices": store.list_voices()}


@app.post("/api/voices", status_code=status.HTTP_201_CREATED)
async def upload_voice(name: str = "", file: UploadFile = File(...)) -> dict:
    from . import audio

    raw = await file.read()
    if len(raw) > config.MAX_VOICE_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="파일이 너무 큽니다 (20MB 이하)")
    if not raw:
        raise HTTPException(status_code=400, detail="빈 파일입니다")

    config.ensure_dirs()
    upload_path = config.UPLOADS_DIR / f"{store.new_id()}{Path(file.filename or '').suffix}"
    upload_path.write_bytes(raw)

    filename = f"{store.new_id()}.wav"
    try:
        duration = audio.to_reference_wav(upload_path, config.VOICES_DIR / filename)
    except audio.AudioError as exc:
        raise HTTPException(status_code=400, detail=f"오디오를 읽지 못했습니다: {exc}") from exc
    finally:
        upload_path.unlink(missing_ok=True)

    if duration < 2.0:
        (config.VOICES_DIR / filename).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="참조 음성은 3초 이상이어야 합니다")

    label = (name or Path(file.filename or "voice").stem)[:80]
    voice_id = store.create_voice(label, filename, duration)
    return {"id": voice_id, "name": label, "duration_sec": duration}


@app.delete("/api/voices/{voice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_voice(voice_id: str) -> None:
    voice = store.get_voice(voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="보이스를 찾을 수 없습니다")
    store.voice_path(voice).unlink(missing_ok=True)
    store.delete_voice(voice_id)


@app.get("/api/voices/{voice_id}/audio")
def voice_audio(voice_id: str):
    voice = store.get_voice(voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="보이스를 찾을 수 없습니다")
    path = store.voice_path(voice)
    if not path.exists():
        raise HTTPException(status_code=404, detail="파일이 없습니다")
    return FileResponse(path, media_type="audio/wav")


# ── 발음 사전 ───────────────────────────────────────────────────────────────


@app.get("/api/dictionary")
def list_dictionary() -> dict:
    return {"entries": store.list_dictionary()}


@app.post("/api/dictionary", status_code=status.HTTP_201_CREATED)
def create_dictionary_entry(payload: DictionaryEntryIn) -> dict:
    entry_id = store.create_dictionary_entry(payload.source.strip(), payload.target.strip())
    return {"id": entry_id}


@app.put("/api/dictionary/{entry_id}")
def update_dictionary_entry(entry_id: str, payload: DictionaryEntryIn) -> dict:
    store.update_dictionary_entry(entry_id, payload.source.strip(), payload.target.strip())
    return {"id": entry_id}


@app.delete("/api/dictionary/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dictionary_entry(entry_id: str) -> None:
    store.delete_dictionary_entry(entry_id)


# ── 정적 프런트엔드 마운트 (반드시 /api/* 뒤) ───────────────────────────────

_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
