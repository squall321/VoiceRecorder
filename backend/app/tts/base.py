# TTS 엔진 공통 인터페이스 — 후처리(속도·간격·병합)는 엔진 밖 audio.py 가 맡는다

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SynthesisRequest:
    """엔진에 넘기는 합성 요청. text 는 이미 정규화(textnorm)를 마친 상태여야 한다."""

    text: str
    language: str = "ko"
    voice_path: Path | None = None
    exaggeration: float = 0.5
    cfg_weight: float = 0.5
    temperature: float = 0.8


@dataclass
class EngineStatus:
    available: bool
    detail: str
    device: str | None = None


class TTSEngine(ABC):
    id: str
    name: str
    description: str
    license: str
    supports_voice_cloning: bool = False

    @abstractmethod
    def languages(self) -> dict[str, str]:
        """지원 언어 코드 → 표시 이름."""

    @abstractmethod
    def status(self) -> EngineStatus:
        """설치·가중치·디바이스 상태. 무거운 로딩 없이 판단할 수 있어야 한다."""

    @abstractmethod
    def sample_rate(self) -> int: ...

    @abstractmethod
    def synthesize(self, request: SynthesisRequest, out_wav: Path) -> float:
        """wav 를 out_wav 에 쓰고 길이(초)를 돌려준다."""

    def warmup(self) -> None:
        """모델을 미리 올려 첫 합성 지연을 없앤다. 실패해도 치명적이지 않다."""
        return None
