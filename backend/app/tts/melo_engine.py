# MeloTTS (MyShell, MIT) 사이드카 엔진 — 별도 venv 에서 subprocess 로 돌린다

from __future__ import annotations

import json
import os
import subprocess
import threading
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


def _melo_installed() -> bool:
    """사이드카 venv 안에 melo 패키지가 실제로 들어있는지 확인한다 (import 는 하지 않는다 —
    이 프로세스의 torch 와 충돌한다)."""
    return any(MELO_PYTHON.parent.parent.glob("lib/python*/site-packages/melo"))


class MeloEngine(TTSEngine):
    id = "melo"
    name = "MeloTTS (CPU)"
    description = "CPU 에서 실시간에 가깝게 도는 경량 엔진. GPU 가 없거나 급할 때 쓴다."
    license = "MIT (코드·가중치 모두)"
    supports_voice_cloning = False

    _SAMPLE_RATE = 44100

    def __init__(self) -> None:
        self._worker: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def status(self) -> EngineStatus:
        if not MELO_PYTHON.exists():
            return EngineStatus(
                False, f"사이드카 venv 없음 — scripts/setup-melo.sh 로 설치 ({MELO_PYTHON})"
            )
        if not MELO_WORKER.exists():
            return EngineStatus(False, f"워커 스크립트 없음: {MELO_WORKER}")
        # venv 파이썬만 보고 판단하면 안 된다 — 설치가 중간에 실패해도 python 바이너리는 남아
        # available=True 로 보고하고, 합성 시점에야 ModuleNotFoundError 로 터진다.
        if not _melo_installed():
            return EngineStatus(
                False, "venv 는 있으나 melo 패키지가 없음 — scripts/setup-melo.sh 를 다시 실행하세요"
            )
        return EngineStatus(True, "준비됨 (CPU 사이드카)", "cpu")

    def languages(self) -> dict[str, str]:
        return dict(_LANGUAGES)

    def sample_rate(self) -> int:
        return self._SAMPLE_RATE

    def _ensure_worker(self) -> subprocess.Popen:
        """상주 워커를 띄워 재사용한다.

        요청마다 프로세스를 새로 띄우면 매번 모델을 다시 올려 씬당 2분이 넘는다.
        죽어 있으면 다시 띄운다.
        """
        if self._worker is not None and self._worker.poll() is None:
            return self._worker
        self._worker = subprocess.Popen(
            [str(MELO_PYTHON), str(MELO_WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        return self._worker

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

        with self._lock:
            worker = self._ensure_worker()
            try:
                worker.stdin.write(payload + "\n")
                worker.stdin.flush()
                line = worker.stdout.readline()
            except (BrokenPipeError, ValueError) as exc:
                self._worker = None
                raise RuntimeError(f"MeloTTS 워커가 죽었습니다: {exc}") from exc

        if not line:
            self._worker = None
            raise RuntimeError("MeloTTS 워커가 응답 없이 종료됐습니다")
        response = json.loads(line)
        if not response.get("ok"):
            raise RuntimeError(f"MeloTTS 합성 실패: {response.get('error')}")
        return probe_duration(out_wav)
