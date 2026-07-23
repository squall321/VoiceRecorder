# 씬 하나를 합성/렌더링하고 프로젝트 전체를 mp3+SRT 로 내보내는 핵심 동작

from __future__ import annotations

from pathlib import Path

from . import audio, config, store
from .textnorm import normalize
from .timeline import build_timeline, render_srt
from .tts import SynthesisRequest, get_engine


def effective_params(project: dict, scene: dict) -> dict:
    """씬 설정이 있으면 씬 것을, 없으면 프로젝트 기본값을 쓴다."""
    return {
        "engine": project["engine"],
        "language": project["language"],
        "voice_id": scene.get("voice_id") or project.get("voice_id"),
        "speed": _first_number(scene.get("speed"), project["speed"], 1.0),
        "gap_before_ms": int(_first_number(scene.get("gap_before_ms"), 0)),
        "gap_after_ms": int(_first_number(scene.get("gap_after_ms"), project["gap_ms"])),
        "exaggeration": _first_number(scene.get("exaggeration"), project["exaggeration"], 0.5),
        "cfg_weight": _first_number(scene.get("cfg_weight"), project["cfg_weight"], 0.5),
        "temperature": _first_number(scene.get("temperature"), project["temperature"], 0.8),
    }


def _first_number(*values) -> float:
    for value in values:
        if value is not None:
            return float(value)
    return 0.0


def normalized_text(project: dict, scene: dict) -> str:
    return normalize(
        scene["text"],
        dictionary=store.dictionary_pairs(),
        read_numbers=bool(project["read_numbers"]),
    )


def current_hash(project: dict, scene: dict) -> str:
    params = effective_params(project, scene)
    return store.synth_hash(
        engine=params["engine"],
        language=params["language"],
        normalized_text=normalized_text(project, scene),
        voice_id=params["voice_id"],
        exaggeration=params["exaggeration"],
        cfg_weight=params["cfg_weight"],
        temperature=params["temperature"],
    )


def scene_status(project: dict, scene: dict) -> str:
    """pending(합성 전) · stale(설정 바뀜) · ready · error"""
    if scene.get("error"):
        return "error"
    if not scene.get("synth_hash"):
        return "pending"
    if not config.scene_raw_path(project["id"], scene["id"]).exists():
        return "pending"
    if scene["synth_hash"] != current_hash(project, scene):
        return "stale"
    if not config.scene_audio_path(project["id"], scene["id"]).exists():
        return "stale"
    return "ready"


def _voice_path(voice_id: str | None) -> Path | None:
    if not voice_id:
        return None
    voice = store.get_voice(voice_id)
    if not voice:
        return None
    path = store.voice_path(voice)
    return path if path.exists() else None


def synthesize_scene(project: dict, scene: dict) -> None:
    """GPU/CPU 로 모델을 돌려 원본 wav 를 만들고 속도까지 반영한다."""
    params = effective_params(project, scene)
    text = normalized_text(project, scene)
    if not text.strip():
        store.set_scene_audio(
            scene["id"],
            synth_hash=None,
            raw_duration_sec=None,
            duration_sec=None,
            error="텍스트가 비어 있습니다",
        )
        return

    raw_path = config.scene_raw_path(project["id"], scene["id"])
    engine = get_engine(params["engine"])
    request = SynthesisRequest(
        text=text,
        language=params["language"],
        voice_path=_voice_path(params["voice_id"]),
        exaggeration=params["exaggeration"],
        cfg_weight=params["cfg_weight"],
        temperature=params["temperature"],
    )

    try:
        raw_duration = engine.synthesize(request, raw_path)
    except Exception as exc:  # noqa: BLE001 - 실패 사유를 그대로 씬에 남긴다
        store.set_scene_audio(
            scene["id"],
            synth_hash=None,
            raw_duration_sec=None,
            duration_sec=None,
            error=str(exc)[:500],
        )
        raise

    duration = _render_speed(project["id"], scene["id"], params["speed"], raw_duration)
    store.set_scene_audio(
        scene["id"],
        synth_hash=current_hash(project, scene),
        raw_duration_sec=raw_duration,
        duration_sec=duration,
        error=None,
    )


def rerender_speed(project: dict, scene: dict) -> bool:
    """속도만 바뀐 경우 — 모델을 다시 돌리지 않고 ffmpeg 로 원본을 다시 렌더링한다."""
    raw_path = config.scene_raw_path(project["id"], scene["id"])
    if not raw_path.exists() or not scene.get("synth_hash"):
        return False
    params = effective_params(project, scene)
    raw_duration = scene.get("raw_duration_sec") or audio.probe_duration(raw_path)
    duration = _render_speed(project["id"], scene["id"], params["speed"], raw_duration)
    store.set_scene_audio(
        scene["id"],
        synth_hash=scene["synth_hash"],
        raw_duration_sec=raw_duration,
        duration_sec=duration,
        error=None,
    )
    return True


def _render_speed(project_id: str, scene_id: str, speed: float, raw_duration: float) -> float:
    raw_path = config.scene_raw_path(project_id, scene_id)
    out_path = config.scene_audio_path(project_id, scene_id)
    audio.apply_speed(raw_path, out_path, speed)
    # atempo 결과 길이는 계산값과 미세하게 다를 수 있어 실제 파일을 다시 잰다
    try:
        return audio.probe_duration(out_path)
    except audio.AudioError:
        return raw_duration / max(speed, 1e-6)


# ── 익스포트 ────────────────────────────────────────────────────────────────


def scene_view(project: dict, scene: dict) -> dict:
    """API 응답·타임라인 계산에 쓰는 씬 표현."""
    params = effective_params(project, scene)
    target = None
    if scene.get("target_start_sec") is not None and scene.get("target_end_sec") is not None:
        span = scene["target_end_sec"] - scene["target_start_sec"]
        target = span if span > 0 else None
    return {
        **scene,
        **{f"effective_{k}": v for k, v in params.items()},
        "gap_before_ms": params["gap_before_ms"],
        "gap_after_ms": params["gap_after_ms"],
        "target_duration_sec": target,
        "status": scene_status(project, scene),
        "normalized_text": normalized_text(project, scene),
    }


def project_timeline(project: dict, scenes: list[dict] | None = None):
    rows = scenes if scenes is not None else store.list_scenes(project["id"])
    views = [scene_view(project, s) for s in rows]
    ready = [v for v in views if v["status"] == "ready"]
    return build_timeline(ready), views


def export_project(project: dict, *, progress=None) -> dict:
    """준비된 씬을 무음 간격과 함께 이어 붙여 mp3 를 만들고 SRT 를 쓴다."""
    timeline, views = project_timeline(project)
    if not timeline.entries:
        raise ValueError("합성된 씬이 없습니다. 먼저 음성을 생성하세요.")

    by_id = {v["id"]: v for v in views}
    engine = get_engine(project["engine"])
    sample_rate = engine.sample_rate()
    # 무음은 실제 씬 wav 와 샘플레이트가 같아야 concat 이 통과한다.
    first_scene = config.scene_audio_path(project["id"], timeline.entries[0].scene_id)
    sample_rate = _probe_sample_rate(first_scene, sample_rate)

    work_dir = config.project_dir(project["id"]) / "export" / "parts"
    work_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    silence_cache: dict[int, Path] = {}

    def silence(ms: int) -> Path | None:
        if ms <= 0:
            return None
        cached = silence_cache.get(ms)
        if cached is None:
            cached = work_dir / f"sil_{ms}.wav"
            audio.make_silence(cached, ms / 1000.0, sample_rate)
            silence_cache[ms] = cached
        return cached

    for position, entry in enumerate(timeline.entries):
        view = by_id[entry.scene_id]
        lead = silence(int(view["gap_before_ms"]))
        if lead:
            parts.append(lead)
        parts.append(config.scene_audio_path(project["id"], entry.scene_id))
        tail = silence(int(view["gap_after_ms"]))
        if tail:
            parts.append(tail)
        if progress:
            progress(position + 1, len(timeline.entries))

    mp3_path = config.export_mp3_path(project["id"])
    audio.concat_to_mp3(parts, mp3_path, bitrate=config.MP3_BITRATE)

    srt_path = config.export_srt_path(project["id"])
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    srt_path.write_text(render_srt(timeline), encoding="utf-8")

    return {
        "scene_count": len(timeline.entries),
        "total_sec": round(timeline.total_sec, 3),
        "mp3_bytes": mp3_path.stat().st_size,
        "mp3": mp3_path.name,
        "srt": srt_path.name,
    }


def _probe_sample_rate(path: Path, fallback: int) -> int:
    import wave

    try:
        with wave.open(str(path), "rb") as fh:
            return fh.getframerate()
    except Exception:  # noqa: BLE001 - 못 읽으면 엔진 기본값을 쓴다
        return fallback
