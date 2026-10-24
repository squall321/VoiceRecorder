# 음성 씌우기 원본 영상 — 저장·정보 확인(ffprobe)과 내레이션 먹싱(ffmpeg)

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from . import config
from .audio import FFMPEG, FFPROBE


class VideoError(RuntimeError):
    pass


def _tail(stderr: str | None) -> str:
    return " / ".join((stderr or "").strip().splitlines()[-4:])


def probe(path: Path) -> dict:
    """길이·해상도·코덱·원본 소리 유무. 영상 스트림이 없으면 VideoError."""
    proc = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,duration:stream_disposition=attached_pic",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise VideoError(f"영상 정보를 읽지 못했습니다: {_tail(proc.stderr)}")
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    # mp3 표지 그림도 video 스트림으로 보인다 — attached_pic 은 영상이 아니다
    videos = [
        s
        for s in streams
        if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")
    ]
    if not videos:
        raise VideoError("영상 스트림이 없습니다 (영상 파일을 올려 주세요)")
    # 컨테이너 길이 → 영상 스트림 길이 → 마지막 패킷 시각 순서로 본다. 브라우저 녹화(MediaRecorder)
    # webm 은 컨테이너에 길이가 없어 첫 단계만 보면 멀쩡한 영상을 "길이를 알 수 없다"며 거부했다.
    duration = _as_seconds((data.get("format") or {}).get("duration")) or _as_seconds(videos[0].get("duration"))
    if not duration:
        duration = _last_packet_time(path)
    if not duration:
        raise VideoError("영상 길이를 알 수 없습니다")
    return {
        "duration_sec": round(duration, 3),
        "width": videos[0].get("width"),
        "height": videos[0].get("height"),
        "video_codec": videos[0].get("codec_name"),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def _as_seconds(value) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    return seconds if seconds > 0 else 0.0


def _last_packet_time(path: Path) -> float:
    """영상 패킷의 마지막 표시 시각 — 디코딩 없이 패킷 머리만 읽는다."""
    proc = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    times = [_as_seconds(line.strip().rstrip(",")) for line in proc.stdout.splitlines() if line.strip()]
    return max(times, default=0.0)


# ── 프로젝트에 붙은 영상 ────────────────────────────────────────────────────


def _meta_path(project_id: str) -> Path:
    return config.video_dir(project_id) / "meta.json"


def read_json(path: Path) -> dict | None:
    """깨진(0바이트·반쯤 쓴) JSON 은 '없음'으로 본다 — 파일 하나 때문에 목록 전체가 500 나지 않게."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_json(path: Path, data: dict) -> None:
    """임시 파일에 쓰고 rename — 쓰는 도중 죽어도 이전 내용이 남는다."""
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    part.replace(path)


def read_meta(project_id: str) -> dict | None:
    meta = read_json(_meta_path(project_id))
    if not meta or not meta.get("stored_name"):
        return None
    if not (config.video_dir(project_id) / meta["stored_name"]).exists():
        return None
    return meta


def source_path(project_id: str) -> Path | None:
    meta = read_meta(project_id)
    return config.video_dir(project_id) / meta["stored_name"] if meta else None


def store_upload(project_id: str, uploaded: Path, original_name: str) -> dict:
    """업로드된 임시 파일을 확인하고 프로젝트 영상으로 들인다. 이전 영상·결과는 지운다."""
    info = probe(uploaded)
    remove(project_id)
    folder = config.video_dir(project_id)
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = "source" + (uploaded.suffix.lower() or ".mp4")
    uploaded.replace(folder / stored_name)
    meta = {
        **info,
        "filename": Path(original_name).name[:200] or stored_name,
        "stored_name": stored_name,
        "size_bytes": (folder / stored_name).stat().st_size,
        "uploaded_at": time.time(),
    }
    write_json(_meta_path(project_id), meta)
    return meta


def remove(project_id: str) -> None:
    """영상과, 그 영상으로 만든 결과를 함께 지운다 (결과만 남으면 다른 영상 것으로 오해한다)."""
    shutil.rmtree(config.video_dir(project_id), ignore_errors=True)
    shutil.rmtree(config.dub_dir(project_id), ignore_errors=True)


# ── 먹싱 ────────────────────────────────────────────────────────────────────


def mux(
    video: Path,
    narration_wav: Path,
    out: Path,
    *,
    original_volume: float = 0.0,
    has_audio: bool = False,
) -> dict:
    """영상 + 내레이션 → mp4.

    영상 스트림은 재인코딩 없이 복사한다. mp4 에 못 넣는 코덱(VP8·ProRes 등)이라 실패하면
    H.264 로 다시 인코딩한다. 원본 소리는 volume 0 이면 버리고, 0 보다 크면 그 볼륨으로 깔아
    섞는다 — normalize=0 이라 원본 소리가 있어도 내레이션 크기가 줄지 않는다.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.stem + ".part.mp4")
    mix = original_volume > 0 and has_audio
    if mix:
        audio_map = [
            "-filter_complex",
            f"[0:a:0]volume={original_volume:.3f}[bg];"
            "[1:a:0][bg]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
            "-map",
            "0:v:0",
            "-map",
            "[a]",
        ]
    else:
        audio_map = ["-map", "0:v:0", "-map", "1:a:0"]

    attempts = [
        ["-c:v", "copy"],
        # yuv420p 는 가로·세로가 짝수여야 한다 — 홀수 해상도(161x121 등)는 한 픽셀 깎는다
        [
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
        ],
    ]
    error = ""
    for video_codec in attempts:
        proc = subprocess.run(
            [
                FFMPEG,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(video),
                "-i",
                str(narration_wav),
                *audio_map,
                *video_codec,
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(part),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            part.replace(out)
            return {"video_copied": video_codec[1] == "copy", "original_mixed": mix}
        error = _tail(proc.stderr)
    part.unlink(missing_ok=True)
    raise VideoError(f"영상 합성 실패: {error}")
