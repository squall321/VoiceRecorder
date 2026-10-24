# 씬 하나를 합성/렌더링하고 프로젝트 전체를 mp3+SRT 로 내보내는 핵심 동작

from __future__ import annotations

import hashlib
import json
import shutil
import time
import wave
from pathlib import Path

from . import audio, config, store, video
from .textnorm import latin_words, normalize
from .timeline import build_timeline, place_on_timecode, render_srt
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
        reading=scene.get("reading"),
        read_numbers=bool(project["read_numbers"]),
        language=project["language"],
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


def synthesize_oneshot(tts_id: str, params: dict) -> dict:
    """프로젝트 없이 텍스트 하나를 합성한다 — 외부 연동(길이 실측·미리듣기)용.

    씬 합성과 같은 정규화(발음 사전·숫자 낭독)·엔진 경로를 타되, DB 에 아무것도
    남기지 않고 TTS_DIR 아래 파일만 만든다. 정리는 호출자(DELETE /api/tts/{id}) 몫.
    """
    text = normalize(
        params["text"],
        dictionary=store.dictionary_pairs(),
        read_numbers=bool(params.get("read_numbers", True)),
        language=params.get("language") or config.DEFAULT_LANGUAGE,
    )
    if not text.strip():
        raise ValueError("텍스트가 비어 있습니다")

    engine = get_engine(params.get("engine") or config.DEFAULT_ENGINE)
    voice_path, prompt_text = _voice_ref(params.get("voice_id"))
    request = SynthesisRequest(
        text=text,
        language=params.get("language") or config.DEFAULT_LANGUAGE,
        voice_path=voice_path,
        prompt_text=prompt_text,
        exaggeration=float(params.get("exaggeration", 0.5)),
        cfg_weight=float(params.get("cfg_weight", 0.5)),
        temperature=float(params.get("temperature", 0.8)),
    )

    raw_path = config.tts_raw_path(tts_id)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_duration = engine.synthesize(request, raw_path)

    speed = float(params.get("speed") or 1.0)
    out_path = config.tts_audio_path(tts_id)
    audio.apply_speed(raw_path, out_path, speed)
    try:
        duration = audio.probe_duration(out_path)
    except audio.AudioError:
        duration = raw_duration / max(speed, 1e-6)

    return {
        "tts_id": tts_id,
        "raw_duration_sec": round(raw_duration, 3),
        "duration_sec": round(duration, 3),
        "char_count": len(text),
    }


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

    - 프로젝트 기본 속도(예: 1.2배)로 슬롯에 들어가면: 그 속도를 그대로 따르고 뒤 무음으로 슬롯을 채운다.
      (예전엔 1.0 으로 되돌렸는데, 사용자가 정한 기본 속도보다 느려져 다른 씬과 말빠르기가 달라졌다.)
    - 기본 속도로도 슬롯을 넘으면: 그 씬만 속도를 올려 슬롯에 맞춘다 (max_speed 상한).
    - max_speed 로도 안 들어가면: 속도를 상한에 두고 넘치는 씬으로 리포트한다 (원고 압축 필요).

    원본 wav 를 ffmpeg 로 다시 렌더링만 하므로 모델(GPU)을 다시 돌리지 않는다.
    무음 정렬은 절대 시각 기준이라 한 씬이 살짝 밀려도 다음 여유 씬에서 자동 회수된다.
    """
    over_budget: list[dict] = []
    base = float(project.get("speed") or 1.0)
    # 상한이 기본 속도보다 낮으면 '맞추려다 오히려 느려지는' 일이 생긴다 — 기본 속도 아래로는 내리지 않는다
    ceiling = max(max_speed, base)

    # 1) 씬별 속도 결정
    for scene in store.list_scenes(project["id"]):
        target = _target_duration(scene)
        raw = scene.get("raw_duration_sec")
        if not target or not raw:
            continue
        if raw / base > target + 0.05:
            speed = raw / target
            if speed > ceiling:
                over_budget.append(
                    {
                        "number": scene.get("number"),
                        "title": scene.get("title"),
                        "target_sec": round(target, 2),
                        "min_sec": round(raw / ceiling, 2),  # 상한 배속으로도 이 길이
                    }
                )
                speed = ceiling
            store.update_scene(scene["id"], {"speed": round(speed, 3)})
        else:
            # 씬별 override 를 지워 프로젝트 기본 속도를 따르게 한다
            store.update_scene(scene["id"], {"speed": None})

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
    spoken = normalized_text(project, scene)
    return {
        **scene,
        **{f"effective_{k}": v for k, v in params.items()},
        "gap_before_ms": params["gap_before_ms"],
        "gap_after_ms": params["gap_after_ms"],
        "target_duration_sec": target,
        "status": scene_status(project, scene),
        "normalized_text": spoken,
        # 정규화 뒤에도 남은 영문 — 한국어 합성기가 건너뛸 수 있어 화면에서 읽는 법을 적게 한다
        "unread_latin": latin_words(spoken) if project["language"] == "ko" else [],
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


# ── 음성 씌우기 (영상 더빙) ─────────────────────────────────────────────────


def dub_fingerprint(views: list[dict], meta: dict | None) -> str:
    """결과가 지금 대본·음성·영상과 맞는지 판정하는 지문 — 하나라도 바뀌면 다시 만들어야 한다."""
    parts = [str(meta.get("uploaded_at")) if meta else "-"]
    for v in views:
        parts.append(
            "|".join(
                str(v.get(k))
                for k in (
                    "id",
                    "text",
                    "synth_hash",
                    "duration_sec",
                    "target_start_sec",
                    "target_end_sec",
                    "gap_before_ms",
                    "gap_after_ms",
                    "status",
                )
            )
        )
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def dub_info(project: dict, views: list[dict]) -> dict | None:
    """마지막으로 만든 음성 입힌 영상의 리포트 + 지금 상태와 어긋났는지(stale)."""
    folder = config.dub_dir(project["id"])
    report_path = folder / "result.json"
    if not report_path.exists() or not (folder / "dubbed.mp4").exists():
        return None
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["stale"] = report.get("fingerprint") != dub_fingerprint(views, video.read_meta(project["id"]))
    return report


def dub_project(project: dict, *, original_volume: float = 0.0, progress=None) -> dict:
    """준비된 씬을 타임코드에 배치해 영상에 입힌다 → dubbed.mp4 + narration.mp3 + narration.srt.

    배치 규칙은 timeline.place_on_timecode. 내레이션 트랙은 영상 길이까지 무음으로 채워
    mp3 를 편집기에 0초로 맞춰 올려도 영상과 어긋나지 않게 한다.
    """
    meta = video.read_meta(project["id"])
    source = video.source_path(project["id"])
    if meta is None or source is None:
        raise ValueError("먼저 영상을 올리세요")
    _, views = project_timeline(project)
    if not views:
        raise ValueError("씬이 없습니다")
    not_ready = [v for v in views if v["status"] != "ready"]
    if not_ready:
        raise ValueError(f"음성이 준비되지 않은 씬이 {len(not_ready)}개 있습니다")

    timeline, overruns = place_on_timecode(views)
    total = max(timeline.total_sec, meta["duration_sec"])

    folder = config.dub_dir(project["id"])
    folder.mkdir(parents=True, exist_ok=True)
    placed = folder / "_placed.wav"
    if progress:
        progress(1, "문장 배치")
    _render_placed_wav(project["id"], timeline, placed, total)
    audio.concat_to_mp3([placed], folder / "narration.mp3", bitrate=config.MP3_BITRATE)
    (folder / "narration.srt").write_text(render_srt(timeline), encoding="utf-8")

    if progress:
        progress(2, "영상에 입히는 중")
    try:
        muxed = video.mux(
            source,
            placed,
            folder / "dubbed.mp4",
            original_volume=original_volume,
            has_audio=bool(meta.get("has_audio")),
        )
    finally:
        placed.unlink(missing_ok=True)
        shutil.rmtree(folder / "_conv", ignore_errors=True)

    report = {
        "video_sec": meta["duration_sec"],
        "narration_end_sec": round(timeline.total_sec, 3),
        "total_sec": round(total, 3),
        # 내레이션이 영상 끝을 넘긴 길이 — 플레이어는 마지막 화면을 멈춘 채 소리를 끝까지 낸다
        "beyond_video_sec": round(max(0.0, timeline.total_sec - meta["duration_sec"]), 2),
        "scene_count": len(timeline.entries),
        "overruns": overruns,
        "original_volume": original_volume,
        **muxed,
        "mp4_bytes": (folder / "dubbed.mp4").stat().st_size,
        "created_at": time.time(),
        "fingerprint": dub_fingerprint(views, meta),
    }
    (folder / "result.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return report


def _render_placed_wav(project_id: str, timeline, out: Path, total_sec: float) -> None:
    """씬 wav 를 배치된 시각에 놓아 한 트랙으로 만든다. 사이와 끝은 무음."""
    convert_dir = out.parent / "_conv"
    sources = [config.scene_audio_path(project_id, e.scene_id) for e in timeline.entries]
    rate, channels = _wav_format(sources[0], convert_dir)

    with wave.open(str(out), "wb") as dst:
        dst.setnchannels(channels)
        dst.setsampwidth(2)
        dst.setframerate(rate)
        frame_bytes = 2 * channels
        cursor = 0
        for entry, src in zip(timeline.entries, sources):
            src = _as_pcm16(src, rate, channels, convert_dir)
            with wave.open(str(src), "rb") as fh:
                frames = fh.readframes(fh.getnframes())
            target = int(round(entry.speech_start_sec * rate))
            if target > cursor:
                dst.writeframes(b"\x00" * ((target - cursor) * frame_bytes))
                cursor = target
            dst.writeframes(frames)
            cursor += len(frames) // frame_bytes
        end = int(round(total_sec * rate))
        if end > cursor:
            dst.writeframes(b"\x00" * ((end - cursor) * frame_bytes))


def _wav_format(path: Path, convert_dir: Path) -> tuple[int, int]:
    """첫 씬의 (샘플레이트, 채널) — 트랙 전체를 이 형식으로 맞춘다. 못 읽는 wav 면 16bit 로 바꿔 본다."""
    try:
        with wave.open(str(path), "rb") as fh:
            return fh.getframerate(), fh.getnchannels()
    except (wave.Error, EOFError):
        converted = _convert(path, None, None, convert_dir)
        with wave.open(str(converted), "rb") as fh:
            return fh.getframerate(), fh.getnchannels()


def _as_pcm16(path: Path, rate: int, channels: int, convert_dir: Path) -> Path:
    """엔진을 바꿔 씬마다 형식이 다를 수 있다(멜로 44.1k, 채터박스 24k) — 다르면 맞춰 변환한다."""
    try:
        with wave.open(str(path), "rb") as fh:
            if (fh.getframerate(), fh.getnchannels(), fh.getsampwidth()) == (rate, channels, 2):
                return path
    except (wave.Error, EOFError):
        pass
    return _convert(path, rate, channels, convert_dir)


def _convert(path: Path, rate: int | None, channels: int | None, convert_dir: Path) -> Path:
    dst = convert_dir / f"{path.stem}.wav"
    args = [audio.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path)]
    if channels:
        args += ["-ac", str(channels)]
    if rate:
        args += ["-ar", str(rate)]
    args += ["-c:a", "pcm_s16le", str(dst)]
    dst.parent.mkdir(parents=True, exist_ok=True)
    audio._run(args)
    return dst


def _probe_sample_rate(path: Path, fallback: int) -> int:
    import wave

    try:
        with wave.open(str(path), "rb") as fh:
            return fh.getframerate()
    except Exception:  # noqa: BLE001 - 못 읽으면 엔진 기본값을 쓴다
        return fallback
