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


def _voice_ref(voice_id: str | None) -> tuple[Path | None, str | None]:
    """참조 음성의 (경로, 전사)를 돌려준다. 전사는 CosyVoice 화자 고정에 쓰인다."""
    if not voice_id:
        return None, None
    voice = store.get_voice(voice_id)
    if not voice:
        return None, None
    path = store.voice_path(voice)
    if not path.exists():
        return None, None
    return path, (voice.get("transcript") or None)


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
    voice_path, prompt_text = _voice_ref(params["voice_id"])
    request = SynthesisRequest(
        text=text,
        language=params["language"],
        voice_path=voice_path,
        prompt_text=prompt_text,
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


# ── 타임코드 자동 맞춤 ──────────────────────────────────────────────────────


def _target_duration(scene: dict) -> float | None:
    start, end = scene.get("target_start_sec"), scene.get("target_end_sec")
    if start is None or end is None:
        return None
    span = end - start
    return span if span > 0 else None


def fit_to_timecode(project: dict, *, max_speed: float = 2.0) -> dict:
    """각 씬을 스크립트의 타임코드 슬롯에 맞춘다.

    - 낭독이 슬롯보다 짧으면: 속도 1.0 을 유지하고 뒤 무음으로 슬롯을 채운다 (자연스러움 우선).
    - 낭독이 슬롯보다 길면: 그 씬만 속도를 올려 슬롯에 맞춘다 (max_speed 상한).
    - max_speed 로도 안 들어가면: 속도를 상한에 두고 넘치는 씬으로 리포트한다 (원고 압축 필요).

    원본 wav 를 ffmpeg 로 다시 렌더링만 하므로 모델(GPU)을 다시 돌리지 않는다.
    무음 정렬은 절대 시각 기준이라 한 씬이 살짝 밀려도 다음 여유 씬에서 자동 회수된다.
    """
    over_budget: list[dict] = []

    # 1) 씬별 속도 결정
    for scene in store.list_scenes(project["id"]):
        target = _target_duration(scene)
        raw = scene.get("raw_duration_sec")
        if not target or not raw:
            continue
        if raw > target + 0.05:
            speed = raw / target
            if speed > max_speed:
                over_budget.append(
                    {
                        "number": scene.get("number"),
                        "title": scene.get("title"),
                        "target_sec": round(target, 2),
                        "min_sec": round(raw / max_speed, 2),  # 상한 배속으로도 이 길이
                    }
                )
                speed = max_speed
            store.update_scene(scene["id"], {"speed": round(speed, 3)})
        else:
            store.update_scene(scene["id"], {"speed": 1.0})

    for scene in store.list_scenes(project["id"]):
        rerender_speed(project, scene)

    # 2) 절대 시각 기준 무음 정렬
    scenes = store.list_scenes(project["id"])
    cursor: float | None = None
    for i, scene in enumerate(scenes):
        start_target = scene.get("target_start_sec")
        if cursor is None:
            cursor = start_target or 0.0
            gap_before = int(round(cursor * 1000)) if start_target else 0
        else:
            gap_before = 0
        end = cursor + (scene.get("duration_sec") or 0.0)
        nxt = scenes[i + 1].get("target_start_sec") if i + 1 < len(scenes) else scene.get("target_end_sec")
        if nxt is None:
            nxt = end
        gap_after = max(0, int(round((nxt - end) * 1000)))
        store.update_scene(scene["id"], {"gap_before_ms": gap_before, "gap_after_ms": gap_after})
        cursor = max(end, nxt)

    store.touch_project(project["id"])
    return {"total_sec": round(cursor or 0.0, 3), "over_budget": over_budget}


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
