# 음성 씌우기 — 영상 업로드부터 음성 입힌 mp4 까지 (TTS 만 스텁, ffmpeg 은 실제로 돈다)

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_api import _await_job, client, stub_engine  # noqa: F401 - 픽스처 재사용

from app.audio import FFMPEG, FFPROBE

# 스텁 엔진은 글자당 0.06초 → 1번 씬 1.08초(창 2초에 들어감), 2번 씬 1.38초(창 1초를 넘김)
SCRIPT = """0:00–0:02 첫 문장은 영상 처음에 나옵니다.
0:02–0:03 둘째 문장은 일 초 창에 다 못 들어갑니다.
0:05–0:06 셋째 문장."""


@pytest.fixture(scope="module")
def media(tmp_path_factory) -> dict[str, Path]:
    folder = tmp_path_factory.mktemp("media")

    def make(name: str, *args: str) -> Path:
        out = folder / name
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args, str(out)], check=True)
        return out

    src = ["-f", "lavfi", "-i", "testsrc=duration=6:size=160x120:rate=10"]
    tone = ["-f", "lavfi", "-i", "sine=frequency=500:duration=6"]
    return {
        "mp4": make("clip.mp4", *src, *tone, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"),
        "silent": make("silent.mp4", *src, "-c:v", "libx264", "-pix_fmt", "yuv420p"),
        "webm": make("clip.webm", *src, "-c:v", "libvpx", "-b:v", "200k"),
    }


def _streams(path: Path) -> dict:
    proc = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    return {
        "types": sorted(s["codec_type"] for s in data["streams"]),
        "codecs": {s["codec_type"]: s["codec_name"] for s in data["streams"]},
        "duration": float(data["format"]["duration"]),
    }


def _project(client) -> str:  # noqa: F811
    body = client.post("/api/projects", json={"title": "더빙 테스트", "raw_script": SCRIPT}).json()
    return body["project"]["id"]


def _upload(client, pid: str, path: Path) -> dict:  # noqa: F811
    response = client.put(f"/api/projects/{pid}/video?filename={path.name}", content=path.read_bytes())
    assert response.status_code == 200, response.text
    return response.json()


def _dub(client, pid: str, **options) -> dict:  # noqa: F811
    response = client.post(f"/api/projects/{pid}/dub", json=options)
    assert response.status_code == 202, response.text
    job = _await_job(client, response.json()["job_id"])
    assert job["status"] == "done", job
    return job


def test_upload_rejects_non_video_and_dub_needs_video(client, tmp_path):  # noqa: F811
    pid = _project(client)
    assert client.post(f"/api/projects/{pid}/dub", json={}).status_code == 400

    response = client.put(f"/api/projects/{pid}/video?filename=notes.mp4", content=b"not a video at all")
    assert response.status_code == 400
    assert client.put(f"/api/projects/{pid}/video?filename=empty.mp4", content=b"").status_code == 400
    assert client.get(f"/api/projects/{pid}").json()["video"] is None


def test_uploaded_video_is_described_and_streamable(client, media):  # noqa: F811
    pid = _project(client)
    body = _upload(client, pid, media["mp4"])

    info = body["video"]
    assert info["filename"] == "clip.mp4"
    assert info["duration_sec"] == pytest.approx(6.0, abs=0.2)
    assert (info["width"], info["height"]) == (160, 120)
    assert info["has_audio"] is True

    full = client.get(f"/api/projects/{pid}/video")
    assert full.status_code == 200 and full.headers["content-type"] == "video/mp4"
    # 브라우저 탐색(seek)용 Range 요청
    part = client.get(f"/api/projects/{pid}/video", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100


def test_dub_synthesizes_places_and_muxes(client, stub_engine, media):  # noqa: F811
    pid = _project(client)
    _upload(client, pid, media["mp4"])

    job = _dub(client, pid)
    result = job["result"]
    assert len(stub_engine.calls) == 3  # 미생성 씬을 먼저 합성했다
    assert result["scene_count"] == 3
    assert result["video_copied"] is True
    assert result["video_sec"] == pytest.approx(6.0, abs=0.2)

    # 2번 씬은 창(1초)보다 길어 끝을 넘긴다 — 리포트에만 남고 속도는 그대로다
    over = {o["position"]: o for o in result["overruns"]}
    assert set(over) == {1}
    second = client.get(f"/api/projects/{pid}").json()["scenes"][1]
    assert over[1]["pushed_sec"] == 0.0
    assert over[1]["over_sec"] == pytest.approx(second["duration_sec"] - 1.0, abs=0.01)

    mp4 = client.get(f"/api/projects/{pid}/dub/video")
    assert mp4.status_code == 200
    assert "filename*=utf-8''" in mp4.headers["content-disposition"]
    out = Path(pytest.importorskip("tempfile").mkdtemp()) / "dubbed.mp4"
    out.write_bytes(mp4.content)
    streams = _streams(out)
    assert streams["types"] == ["audio", "video"]
    assert streams["codecs"]["audio"] == "aac"
    assert streams["duration"] >= 5.9

    srt = client.get(f"/api/projects/{pid}/dub/srt").text
    assert "00:00:02,000 -->" in srt and "00:00:05,000 -->" in srt  # 실측 = 타임코드에 고정
    assert "첫 문장은 영상 처음에 나옵니다." in srt
    assert client.get(f"/api/projects/{pid}/dub/audio").headers["content-type"] == "audio/mpeg"

    payload = client.get(f"/api/projects/{pid}").json()
    assert payload["dub"]["stale"] is False


def test_editing_after_dub_marks_result_stale_and_new_video_clears_it(client, media):  # noqa: F811
    pid = _project(client)
    _upload(client, pid, media["mp4"])
    _dub(client, pid)

    scene = client.get(f"/api/projects/{pid}").json()["scenes"][2]
    body = client.patch(f"/api/projects/{pid}/scenes/{scene['id']}", json={"text": "바뀐 셋째 문장."}).json()
    assert body["dub"]["stale"] is True

    body = _upload(client, pid, media["silent"])
    assert body["dub"] is None
    assert body["video"]["has_audio"] is False


def test_original_audio_can_be_mixed_under_narration(client, media):  # noqa: F811
    pid = _project(client)
    _upload(client, pid, media["mp4"])
    result = _dub(client, pid, original_volume=0.3)["result"]
    assert result["original_mixed"] is True


def test_codec_mp4_cannot_hold_is_reencoded(client, media):  # noqa: F811
    pid = _project(client)
    _upload(client, pid, media["webm"])
    result = _dub(client, pid)["result"]
    assert result["video_copied"] is False

    out = Path(pytest.importorskip("tempfile").mkdtemp()) / "dubbed.mp4"
    out.write_bytes(client.get(f"/api/projects/{pid}/dub/video").content)
    assert _streams(out)["codecs"]["video"] == "h264"


def test_narration_longer_than_video_is_reported(client, media):  # noqa: F811
    script = "0:00–0:05 " + "아주 긴 문장이 영상이 끝난 뒤에도 계속 이어집니다. " * 3 + "\n0:05 끝."
    # 속도를 1.0 으로 못 박는다 — 기본 속도(1.2)가 바뀌어도 '영상보다 길다' 조건이 유지되게
    body = {"title": "긴 내레이션", "raw_script": script, "speed": 1.0}
    pid = client.post("/api/projects", json=body).json()["project"]["id"]
    _upload(client, pid, media["silent"])
    result = _dub(client, pid)["result"]
    assert result["beyond_video_sec"] > 0
    assert result["total_sec"] == pytest.approx(result["narration_end_sec"])


def test_delete_video_removes_results(client, media):  # noqa: F811
    pid = _project(client)
    _upload(client, pid, media["mp4"])
    _dub(client, pid)

    body = client.delete(f"/api/projects/{pid}/video").json()
    assert body["video"] is None and body["dub"] is None
    assert client.get(f"/api/projects/{pid}/dub/video").status_code == 404


def test_video_change_blocked_while_any_dub_job_is_pending(client, media):  # noqa: F811
    # 최신 작업만 보던 검사는 더빙 뒤에 줄 선 합성 작업에 가려 영상 교체를 통과시켰다
    from app import store

    pid = _project(client)
    _upload(client, pid, media["mp4"])
    store.create_job(pid, "dub", 3)  # 대기 중인 더빙(러너에 넣지 않은 기록만)
    store.create_job(pid, "synthesize", 1)  # 그 뒤에 줄 선 다른 작업

    response = client.put(f"/api/projects/{pid}/video?filename=again.mp4", content=media["silent"].read_bytes())
    assert response.status_code == 409
    assert client.delete(f"/api/projects/{pid}/video").status_code == 409
    assert client.post(f"/api/projects/{pid}/dub", json={}).status_code == 409


def test_project_list_shows_video_and_dub_badges(client, media):  # noqa: F811
    pid = _project(client)

    def row():
        return next(p for p in client.get("/api/projects").json()["projects"] if p["id"] == pid)

    assert (row()["has_video"], row()["has_dub"]) == (False, False)
    _upload(client, pid, media["mp4"])
    assert (row()["has_video"], row()["has_dub"]) == (True, False)
    _dub(client, pid)
    assert (row()["has_video"], row()["has_dub"]) == (True, True)


def test_upload_suffix_cannot_turn_video_into_html(client, media):  # noqa: F811
    # ?filename=x.html 로 올려도 영상 확장자로 저장하고, 영상 응답은 video/* 또는 octet-stream + nosniff
    pid = _project(client)
    response = client.put(f"/api/projects/{pid}/video?filename=evil.html", content=media["mp4"].read_bytes())
    assert response.status_code == 200
    assert response.json()["video"]["stored_name"] == "source.mp4"

    served = client.get(f"/api/projects/{pid}/video")
    assert served.headers["content-type"] == "video/mp4"
    assert served.headers["x-content-type-options"] == "nosniff"


# ── 견고성 (리뷰에서 재현된 것들) ───────────────────────────────────────────


def test_webm_without_container_duration_is_accepted(client, tmp_path):  # noqa: F811
    # 파이프로 쓴 webm(브라우저 녹화와 같다)은 컨테이너에 길이가 없다 — 스트림·패킷 시각으로 잰다
    out = tmp_path / "piped.webm"
    with out.open("wb") as fh:
        subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=3:size=160x120:rate=10",
             "-c:v", "libvpx", "-b:v", "100k", "-f", "webm", "pipe:1"],
            stdout=fh, check=True,
        )
    pid = _project(client)
    body = _upload(client, pid, out)
    assert body["video"]["duration_sec"] == pytest.approx(3.0, abs=0.3)


def test_odd_sized_video_is_reencoded_with_even_dimensions(client, tmp_path):  # noqa: F811
    src = tmp_path / "odd.webm"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=6:size=161x121:rate=10",
         "-c:v", "libvpx", "-b:v", "100k", str(src)],
        check=True,
    )
    pid = _project(client)
    _upload(client, pid, src)
    result = _dub(client, pid)["result"]
    assert result["video_copied"] is False


def test_broken_meta_or_result_json_does_not_break_listing(client, media):  # noqa: F811
    from app import config

    pid = _project(client)
    _upload(client, pid, media["mp4"])
    _dub(client, pid)
    (config.video_dir(pid) / "meta.json").write_text("", encoding="utf-8")
    (config.dub_dir(pid) / "result.json").write_text("{", encoding="utf-8")

    assert client.get("/api/projects").status_code == 200
    body = client.get(f"/api/projects/{pid}").json()
    assert body["video"] is None and body["dub"] is None


def test_declared_oversize_upload_is_rejected_before_streaming(client, monkeypatch, media):  # noqa: F811
    from app import config

    monkeypatch.setattr(config, "MAX_VIDEO_UPLOAD_BYTES", 1000)
    pid = _project(client)
    response = client.put(f"/api/projects/{pid}/video?filename=big.mp4", content=media["mp4"].read_bytes())
    assert response.status_code == 413
    assert list(config.UPLOADS_DIR.glob("video-*")) == []


def test_failed_dub_leaves_no_temp_files_and_keeps_previous_result(client, media):  # noqa: F811
    from app import config

    pid = _project(client)
    _upload(client, pid, media["mp4"])
    _dub(client, pid)
    folder = config.dub_dir(pid)
    before = (folder / "narration.srt").read_text(encoding="utf-8")

    # 씬 wav 하나를 망가뜨리고 다시 만든다 → 실패해도 임시 파일이 없고 이전 결과 세트가 그대로다
    scene = client.get(f"/api/projects/{pid}").json()["scenes"][0]
    config.scene_audio_path(pid, scene["id"]).write_bytes(b"not a wav")
    response = client.post(f"/api/projects/{pid}/dub", json={})
    job = _await_job(client, response.json()["job_id"])
    assert job["status"] == "error"
    assert sorted(p.name for p in folder.iterdir()) == ["dubbed.mp4", "narration.mp3", "narration.srt", "result.json"]
    assert (folder / "narration.srt").read_text(encoding="utf-8") == before
