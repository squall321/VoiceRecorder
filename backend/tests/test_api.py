# API 통합 테스트 — TTS 엔진만 스텁으로 갈아끼우고 나머지(ffmpeg 병합·SRT)는 실제로 돌린다

from __future__ import annotations

import math
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import store
from app.main import app
from app.tts import registry
from app.tts.base import EngineStatus, SynthesisRequest, TTSEngine

SCRIPT = """01 오프닝 (0:00–0:08) "질문 하나가 의사결정문이 되기까지 — HWAX 협업진단 플랫폼."

02 문제 배정 (0:08–0:19) "신제품 초기안의 최고 온도는 83.4도. 허용 기준을 넘겼습니다."

03 아웃트로 (0:19–0:27) "질문을 던지세요. 전문가 회의가 열립니다."
"""

SAMPLE_RATE = 24000


class StubEngine(TTSEngine):
    """글자 수에 비례한 길이의 톤을 만든다 — GPU 없이 파이프라인 전체를 검증하려고."""

    id = "chatterbox"  # 기본 엔진 자리를 그대로 차지한다
    name = "Stub"
    description = "테스트용"
    license = "MIT"
    supports_voice_cloning = True

    def __init__(self) -> None:
        self.calls: list[SynthesisRequest] = []

    def languages(self) -> dict[str, str]:
        return {"ko": "Korean"}

    def status(self) -> EngineStatus:
        return EngineStatus(True, "테스트 스텁", "cpu")

    def sample_rate(self) -> int:
        return SAMPLE_RATE

    def synthesize(self, request: SynthesisRequest, out_wav: Path) -> float:
        self.calls.append(request)
        duration = max(0.5, len(request.text) * 0.06)
        frames = bytearray()
        for n in range(int(duration * SAMPLE_RATE)):
            value = int(12000 * math.sin(2 * math.pi * 220 * n / SAMPLE_RATE))
            frames += int(value).to_bytes(2, "little", signed=True)
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_wav), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(SAMPLE_RATE)
            fh.writeframes(bytes(frames))
        return duration


@pytest.fixture()
def stub_engine():
    engine = StubEngine()
    registry._ENGINES.clear()
    registry._ENGINES["chatterbox"] = engine
    yield engine
    registry._ENGINES.clear()


@pytest.fixture()
def client(stub_engine):
    with TestClient(app) as test_client:
        yield test_client


def _create(client) -> dict:
    response = client.post("/api/projects", json={"title": "테스트", "raw_script": SCRIPT})
    assert response.status_code == 201, response.text
    return response.json()


def _synthesize(client, project_id: str, **payload) -> dict:
    response = client.post(f"/api/projects/{project_id}/synthesize", json=payload)
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    return _await_job(client, job_id)


def _await_job(client, job_id: str) -> dict:
    for _ in range(600):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        import time

        time.sleep(0.05)
    raise AssertionError("작업이 끝나지 않았습니다")


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_engines_report_license_and_availability(client):
    body = client.get("/api/engines").json()
    assert body["engines"][0]["available"] is True
    assert "MIT" in body["engines"][0]["license"]


def test_parse_endpoint_returns_scenes_with_targets(client):
    body = client.post("/api/scripts/parse", json={"raw_script": SCRIPT}).json()

    assert body["structured"] is True
    assert len(body["scenes"]) == 3
    assert body["scenes"][0]["target_duration_sec"] == 8.0
    assert body["scenes"][0]["title"] == "오프닝"


def test_create_project_splits_scenes(client):
    body = _create(client)

    assert len(body["scenes"]) == 3
    assert [s["number"] for s in body["scenes"]] == [1, 2, 3]
    assert all(s["status"] == "pending" for s in body["scenes"])
    assert body["ready_count"] == 0


def test_synthesis_makes_every_scene_ready(client):
    project = _create(client)
    pid = project["project"]["id"]

    job = _synthesize(client, pid)
    assert job["status"] == "done", job

    body = client.get(f"/api/projects/{pid}").json()
    assert body["ready_count"] == 3
    assert all(s["duration_sec"] > 0 for s in body["scenes"])
    assert body["total_sec"] > 0


def test_scene_audio_is_downloadable(client):
    project = _create(client)
    pid = project["project"]["id"]
    _synthesize(client, pid)

    scene_id = client.get(f"/api/projects/{pid}").json()["scenes"][0]["id"]
    response = client.get(f"/api/projects/{pid}/scenes/{scene_id}/audio")

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert len(response.content) > 1000


def test_editing_text_marks_only_that_scene_stale(client, stub_engine):
    project = _create(client)
    pid = project["project"]["id"]
    _synthesize(client, pid)
    scenes = client.get(f"/api/projects/{pid}").json()["scenes"]
    target = scenes[1]

    body = client.patch(
        f"/api/projects/{pid}/scenes/{target['id']}", json={"text": "완전히 다른 문장입니다."}
    ).json()

    statuses = {s["id"]: s["status"] for s in body["scenes"]}
    assert statuses[target["id"]] == "stale"
    assert statuses[scenes[0]["id"]] == "ready"
    assert statuses[scenes[2]["id"]] == "ready"

    # 재합성은 stale 한 씬 하나만 돈다
    before = len(stub_engine.calls)
    _synthesize(client, pid)
    assert len(stub_engine.calls) == before + 1


def test_speed_change_does_not_call_the_model_again(client, stub_engine):
    project = _create(client)
    pid = project["project"]["id"]
    _synthesize(client, pid)
    scenes = client.get(f"/api/projects/{pid}").json()["scenes"]
    target = scenes[0]
    original = target["duration_sec"]
    calls = len(stub_engine.calls)

    body = client.patch(f"/api/projects/{pid}/scenes/{target['id']}", json={"speed": 1.5}).json()
    updated = next(s for s in body["scenes"] if s["id"] == target["id"])

    assert len(stub_engine.calls) == calls  # 모델 재호출 없음
    assert updated["status"] == "ready"
    assert updated["duration_sec"] == pytest.approx(original / 1.5, rel=0.05)


def test_apply_speed_unifies_all_scenes_including_overrides(client, stub_engine):
    project = _create(client)
    pid = project["project"]["id"]
    _synthesize(client, pid)
    scenes = client.get(f"/api/projects/{pid}").json()["scenes"]

    # 씬 하나에만 개별 속도를 건다 — 이러면 전체 슬라이더를 따르지 않는다
    client.patch(f"/api/projects/{pid}/scenes/{scenes[0]['id']}", json={"speed": 0.8})
    body = client.get(f"/api/projects/{pid}").json()
    assert body["scenes"][0]["speed"] == 0.8
    assert body["scenes"][1]["speed"] is None

    calls_before = len(stub_engine.calls)
    body = client.post(f"/api/projects/{pid}/apply-speed", json={"speed": 1.5}).json()

    # 모든 씬의 override 가 지워지고 프로젝트 속도가 1.5 로 통일된다
    assert body["project"]["speed"] == 1.5
    assert all(s["speed"] is None for s in body["scenes"])
    assert all(abs(s["effective_speed"] - 1.5) < 1e-6 for s in body["scenes"])
    # 텍스트는 그대로라 모델을 다시 호출하지 않는다 (ffmpeg 재렌더만)
    assert len(stub_engine.calls) == calls_before
    assert all(s["status"] == "ready" for s in body["scenes"])


def test_apply_speed_rejects_out_of_range(client):
    project = _create(client)
    pid = project["project"]["id"]
    assert client.post(f"/api/projects/{pid}/apply-speed", json={"speed": 3.0}).status_code == 422


def test_fit_timecode_aligns_scenes_to_slots(client):
    project = _create(client)
    pid = project["project"]["id"]
    _synthesize(client, pid)

    body = client.post(f"/api/projects/{pid}/fit-timecode", json={}).json()
    scenes = body["scenes"]

    # 스텁은 글자수×0.06초로 합성한다. SCRIPT 의 슬롯(8/11/8초)보다 짧아 무음으로 채워지고,
    # 각 씬 시작이 타임코드 목표(0, 8, 19초)에 정확히 앉는다.
    assert body["fit_report"]["over_budget"] == []
    assert scenes[0]["start_sec"] == 0.0
    assert scenes[1]["start_sec"] == pytest.approx(8.0, abs=0.05)
    assert scenes[2]["start_sec"] == pytest.approx(19.0, abs=0.05)


def test_fit_timecode_speeds_up_overshooting_scene(client, stub_engine):
    # 슬롯보다 긴 씬을 만든다: 4초 슬롯에 긴 문장
    long_text = "가나다라마바사아자차카타파하" * 4  # 스텁 기준 약 3.4초... 더 길게
    raw = f'01 긴씬 (0:00–0:02) "{long_text}"\n\n02 짧은씬 (0:02–0:10) "짧다."'
    pid = client.post("/api/projects", json={"title": "t", "raw_script": raw}).json()["project"]["id"]
    _synthesize(client, pid)

    calls_before = len(stub_engine.calls)
    body = client.post(f"/api/projects/{pid}/fit-timecode", json={"max_speed": 2.0}).json()
    first = body["scenes"][0]

    # 2초 슬롯을 넘는 씬은 배속이 올라간다 (모델 재호출 없이 ffmpeg 재렌더)
    assert first["effective_speed"] > 1.0
    assert len(stub_engine.calls) == calls_before
    # 2배로도 안 들어가면 over_budget 에 보고된다
    assert isinstance(body["fit_report"]["over_budget"], list)


def test_fit_timecode_requires_all_ready(client):
    project = _create(client)
    pid = project["project"]["id"]
    # 합성 전이라 거부
    assert client.post(f"/api/projects/{pid}/fit-timecode", json={}).status_code == 400


def test_drift_against_script_timecode_is_reported(client):
    project = _create(client)
    pid = project["project"]["id"]
    _synthesize(client, pid)

    scenes = client.get(f"/api/projects/{pid}").json()["scenes"]
    first = scenes[0]

    assert first["target_duration_sec"] == 8.0
    assert first["drift_sec"] == pytest.approx(first["duration_sec"] - 8.0, abs=0.01)


def test_reorder_changes_timeline_order(client):
    project = _create(client)
    pid = project["project"]["id"]
    _synthesize(client, pid)
    scenes = client.get(f"/api/projects/{pid}").json()["scenes"]
    reversed_ids = [s["id"] for s in reversed(scenes)]

    body = client.post(f"/api/projects/{pid}/scenes/reorder", json={"scene_ids": reversed_ids}).json()

    assert [s["id"] for s in body["scenes"]] == reversed_ids
    assert body["scenes"][0]["start_sec"] == 0.0


def test_reorder_rejects_mismatched_ids(client):
    project = _create(client)
    pid = project["project"]["id"]

    response = client.post(f"/api/projects/{pid}/scenes/reorder", json={"scene_ids": ["nope"]})
    assert response.status_code == 400


def test_scene_add_and_delete(client):
    project = _create(client)
    pid = project["project"]["id"]
    scenes = project["scenes"]

    body = client.post(
        f"/api/projects/{pid}/scenes",
        json={"text": "끼워 넣은 씬.", "after_scene_id": scenes[0]["id"]},
    ).json()
    assert len(body["scenes"]) == 4
    assert body["scenes"][1]["text"] == "끼워 넣은 씬."

    body = client.delete(f"/api/projects/{pid}/scenes/{body['scenes'][1]['id']}").json()
    assert len(body["scenes"]) == 3
    assert [s["position"] for s in body["scenes"]] == [0, 1, 2]


def test_export_produces_mp3_and_srt(client):
    project = _create(client)
    pid = project["project"]["id"]
    _synthesize(client, pid)

    response = client.post(f"/api/projects/{pid}/export")
    assert response.status_code == 202
    job = _await_job(client, response.json()["job_id"])
    assert job["status"] == "done", job
    assert job["result"]["scene_count"] == 3
    assert job["result"]["mp3_bytes"] > 5000

    mp3 = client.get(f"/api/projects/{pid}/export/audio")
    assert mp3.status_code == 200
    assert mp3.headers["content-type"] == "audio/mpeg"
    assert mp3.content[:3] in (b"ID3", b"\xff\xfb\x00") or mp3.content[0] == 0xFF

    srt = client.get(f"/api/projects/{pid}/export/srt")
    assert srt.status_code == 200
    assert srt.text.startswith("1\n00:00:00,000 --> ")
    assert srt.text.count(" --> ") == 3


def test_exported_mp3_length_matches_timeline(client):
    project = _create(client)
    pid = project["project"]["id"]
    _synthesize(client, pid)
    _await_job(client, client.post(f"/api/projects/{pid}/export").json()["job_id"])

    from app import audio, config

    total = client.get(f"/api/projects/{pid}").json()["total_sec"]
    actual = audio.probe_duration(config.export_mp3_path(pid))

    # mp3 인코더가 앞뒤로 약간의 패딩을 넣어 오차 허용
    assert actual == pytest.approx(total, abs=0.2)


def test_gap_change_lengthens_the_export(client):
    project = _create(client)
    pid = project["project"]["id"]
    _synthesize(client, pid)
    before = client.get(f"/api/projects/{pid}").json()["total_sec"]

    body = client.patch(f"/api/projects/{pid}", json={"gap_ms": 1200}).json()

    assert body["total_sec"] > before


def test_dictionary_affects_synthesis_input(client, stub_engine):
    client.post("/api/dictionary", json={"source": "HWAX", "target": "에이치왁스"})
    project = _create(client)
    pid = project["project"]["id"]
    _synthesize(client, pid)

    assert any("에이치왁스" in call.text for call in stub_engine.calls)
    assert not any("HWAX" in call.text for call in stub_engine.calls)


def test_numbers_are_read_in_korean(client, stub_engine):
    project = _create(client)
    _synthesize(client, project["project"]["id"])

    assert any("팔십삼 점 사" in call.text for call in stub_engine.calls)


def test_replacing_the_script_resets_scenes(client):
    project = _create(client)
    pid = project["project"]["id"]
    _synthesize(client, pid)

    body = client.put(
        f"/api/projects/{pid}/script", json={"raw_script": '01 새 씬 (0:00–0:04) "새로운 내용."'}
    ).json()

    assert len(body["scenes"]) == 1
    assert body["scenes"][0]["status"] == "pending"
    assert body["ready_count"] == 0


def test_synthesize_rejects_when_everything_is_ready(client):
    project = _create(client)
    pid = project["project"]["id"]
    _synthesize(client, pid)

    response = client.post(f"/api/projects/{pid}/synthesize", json={})
    assert response.status_code == 400


def test_export_requires_synthesized_scenes(client):
    project = _create(client)
    response = client.post(f"/api/projects/{project['project']['id']}/export")
    assert response.status_code == 400


def test_project_delete_removes_everything(client):
    project = _create(client)
    pid = project["project"]["id"]
    _synthesize(client, pid)

    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.get(f"/api/projects/{pid}").status_code == 404
    assert store.get_project(pid) is None


def test_unknown_project_is_404(client):
    assert client.get("/api/projects/nope").status_code == 404


def test_empty_script_is_rejected(client):
    response = client.post("/api/projects", json={"title": "빈", "raw_script": "   "})
    assert response.status_code == 400
