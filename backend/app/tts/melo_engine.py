# MeloTTS (MyShell, MIT) 사이드카 엔진 — 별도 venv 에서 subprocess 로 돌린다

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from ..audio import probe_duration
from .base import EngineStatus, SynthesisRequest, TTSEngine

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_REPO_ROOT = _BACKEND_DIR.parent

# 왜 별도 venv 인가:
#   MeloTTS 는 torch<2.0, transformers==4.27.4, librosa==0.9.1 을 핀한다.
#   Chatterbox 는 torch>=2.6, transformers==5.2.0 을 요구한다. 한 venv 에 공존 불가라
#   scripts/setup-melo.sh 가 .venv-melo 를 따로 만들고 여기서는 subprocess 로만 호출한다.
MELO_PYTHON = Path(
    os.environ.get("VOICEREC_MELO_PYTHON") or (_BACKEND_DIR / ".venv-melo" / "bin" / "python")
)
MELO_WORKER = _REPO_ROOT / "scripts" / "melo_worker.py"

_LANGUAGES = {
    "ko": "Korean",
    "en": "English",
    "ja": "Japanese",
    "zh": "Chinese",
    "es": "Spanish",
    "fr": "French",
}

_LANG_TO_MELO = {"ko": "KR", "en": "EN", "ja": "JP", "zh": "ZH", "es": "ES", "fr": "FR"}


class MeloEngine(TTSEngine):
    id = "melo"
    name = "MeloTTS (CPU)"
    description = "CPU 에서 실시간에 가깝게 도는 경량 엔진. GPU 가 없거나 급할 때 쓴다."
    license = "MIT (코드·가중치 모두)"
    supports_voice_cloning = False

    _SAMPLE_RATE = 44100

    def status(self) -> EngineStatus:
        if not MELO_PYTHON.exists():
            return EngineStatus(
                False, f"사이드카 venv 없음 — scripts/setup-melo.sh 로 설치 ({MELO_PYTHON})"
            )
        if not MELO_WORKER.exists():
            return EngineStatus(False, f"워커 스크립트 없음: {MELO_WORKER}")
        return EngineStatus(True, "준비됨 (CPU 사이드카)", "cpu")

    def languages(self) -> dict[str, str]:
        return dict(_LANGUAGES)

    def sample_rate(self) -> int:
        return self._SAMPLE_RATE

    def synthesize(self, request: SynthesisRequest, out_wav: Path) -> float:
        status = self.status()
        if not status.available:
            raise RuntimeError(status.detail)

        melo_lang = _LANG_TO_MELO.get(request.language)
        if melo_lang is None:
            raise ValueError(f"MeloTTS 가 지원하지 않는 언어: {request.language}")

        out_wav.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"text": request.text, "language": melo_lang, "out": str(out_wav)},
            ensure_ascii=False,
        )
        proc = subprocess.run(
            [str(MELO_PYTHON), str(MELO_WORKER)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()[-5:]
            raise RuntimeError("MeloTTS 합성 실패: " + " / ".join(tail))
        return probe_duration(out_wav)
