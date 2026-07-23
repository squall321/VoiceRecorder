# ffmpeg 로 속도 조절·무음 삽입·병합·mp3 인코딩을 처리한다 (TTS 엔진과 무관한 후처리)

from __future__ import annotations

import array
import json
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

MIN_SPEED = 0.5
MAX_SPEED = 2.0


class AudioError(RuntimeError):
    pass


def _run(args: list[str]) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise AudioError(f"{args[0]} 실패 (code {proc.returncode}): " + " / ".join(tail))


def probe_duration(path: Path) -> float:
    """오디오 길이(초). ffprobe 가 못 읽으면 AudioError."""
    proc = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AudioError(f"ffprobe 실패: {path}")
    try:
        return float(json.loads(proc.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise AudioError(f"길이를 읽지 못함: {path}") from exc


def write_wav_frames(dst: Path, frames: bytes, sample_rate: int, channels: int = 1) -> float:
    """16bit PCM 프레임을 wav 로 쓰고 길이(초)를 돌려준다.

    torchaudio 2.11 부터 save() 가 인코딩을 torchcodec 에 위임하는데, 그 패키지를 깔면
    torch 버전 제약이 하나 더 늘어난다. wav 쓰기는 stdlib 로 충분해서 의존성을 안 늘린다.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dst), "wb") as fh:
        fh.setnchannels(channels)
        fh.setsampwidth(2)
        fh.setframerate(sample_rate)
        fh.writeframes(frames)
    return len(frames) / 2 / channels / float(sample_rate)


def write_wav_pcm16(dst: Path, samples, sample_rate: int, channels: int = 1) -> float:
    """float(-1~1) 시퀀스를 16bit PCM wav 로 쓴다."""
    clipped = array.array("h", (int(max(-1.0, min(1.0, s)) * 32767.0) for s in samples))
    return write_wav_frames(dst, clipped.tobytes(), sample_rate, channels)


def _atempo_chain(speed: float) -> str:
    """atempo 는 한 번에 0.5~2.0 만 받는다. 범위를 벗어나면 여러 단으로 체이닝한다."""
    filters: list[str] = []
    remaining = speed
    while remaining > MAX_SPEED:
        filters.append(f"atempo={MAX_SPEED}")
        remaining /= MAX_SPEED
    while remaining < MIN_SPEED:
        filters.append(f"atempo={MIN_SPEED}")
        remaining /= MIN_SPEED
    filters.append(f"atempo={remaining:.6f}")
    return ",".join(filters)


def apply_speed(src: Path, dst: Path, speed: float) -> None:
    """말 속도 조절. 피치는 유지된다(atempo). speed=1.0 이면 그냥 복사."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if abs(speed - 1.0) < 1e-3:
        if src.resolve() != dst.resolve():
            shutil.copyfile(src, dst)
        return
    _run(
        [
            FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-filter:a",
            _atempo_chain(speed),
            "-c:a",
            "pcm_s16le",
            str(dst),
        ]
    )


def make_silence(dst: Path, seconds: float, sample_rate: int, channels: int = 1) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    layout = "mono" if channels == 1 else "stereo"
    _run(
        [
            FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={sample_rate}:cl={layout}",
            "-t",
            f"{max(seconds, 0.0):.3f}",
            "-c:a",
            "pcm_s16le",
            str(dst),
        ]
    )


def concat_to_mp3(parts: list[Path], dst: Path, *, bitrate: str = "192k") -> None:
    """wav 조각들을 순서대로 이어 붙여 mp3 로 인코딩한다.

    concat demuxer 는 입력의 샘플레이트·채널이 같아야 한다. 여기 들어오는 조각은 전부
    같은 엔진 출력이거나 그 샘플레이트로 만든 무음이라 조건을 만족한다.
    """
    if not parts:
        raise AudioError("병합할 오디오가 없습니다")
    dst.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        for part in parts:
            escaped = str(part.resolve()).replace("'", r"'\''")
            fh.write(f"file '{escaped}'\n")
        list_path = Path(fh.name)

    try:
        _run(
            [
                FFMPEG,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c:a",
                "libmp3lame",
                "-b:a",
                bitrate,
                str(dst),
            ]
        )
    finally:
        list_path.unlink(missing_ok=True)


def to_reference_wav(src: Path, dst: Path, *, sample_rate: int = 24000) -> float:
    """업로드된 참조 음성을 엔진이 받는 모노 wav 로 변환하고 길이를 돌려준다."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(dst),
        ]
    )
    return probe_duration(dst)
