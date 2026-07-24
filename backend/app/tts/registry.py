# 사용 가능한 TTS 엔진을 모아 이름으로 찾아준다

from __future__ import annotations

from .base import TTSEngine
from .chatterbox_engine import ChatterboxEngine
from .cosy_engine import CosyEngine
from .melo_engine import MeloEngine

_ENGINES: dict[str, TTSEngine] = {}


def _registry() -> dict[str, TTSEngine]:
    if not _ENGINES:
        for engine in (ChatterboxEngine(), MeloEngine(), CosyEngine()):
            _ENGINES[engine.id] = engine
    return _ENGINES


def get_engine(engine_id: str) -> TTSEngine:
    engine = _registry().get(engine_id)
    if engine is None:
        raise KeyError(f"알 수 없는 엔진: {engine_id}")
    return engine


def describe_engines() -> list[dict]:
    """UI 가 엔진 선택지를 그리는 데 쓰는 요약."""
    out: list[dict] = []
    for engine in _registry().values():
        status = engine.status()
        out.append(
            {
                "id": engine.id,
                "name": engine.name,
                "description": engine.description,
                "license": engine.license,
                "supports_voice_cloning": engine.supports_voice_cloning,
                "languages": engine.languages(),
                "available": status.available,
                "detail": status.detail,
                "device": status.device,
            }
        )
    return out


def first_available() -> TTSEngine | None:
    for engine in _registry().values():
        if engine.status().available:
            return engine
    return None
