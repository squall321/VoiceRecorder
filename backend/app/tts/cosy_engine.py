# CosyVoice 3 (FunAudioLLM, Apache-2.0) 사이드카 엔진 — 별도 venv 에서 subprocess 상주 워커로 돈다

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
#   CosyVoice 는 torch==2.3.1(cu121) 을 핀한다. Chatterbox 는 torch 2.13/cu130 을 쓰므로 공존 불가.
#   또 cu121 휠에는 RTX 50 시리즈(sm_120) 커널이 없어 GPU 를 못 쓴다 → CPU 사이드카로 둔다.
#   설치: scripts/setup-cosy.sh (repo clone + .venv-cosy + 가중치)
COSY_PYTHON = Path(
    os.environ.get("VOICEREC_COSY_PYTHON") or (_BACKEND_DIR / ".venv-cosy" / "bin" / "python")
)
COSY_REPO = Path(os.environ.get("VOICEREC_COSY_REPO") or (_REPO_ROOT / "vendor" / "CosyVoice"))
COSY_WORKER = _REPO_ROOT / "scripts" / "cosy_worker.py"

_LANGUAGES = {
    "ko": "Korean",
    "en": "English",
    "ja": "Japanese",
    "zh": "Chinese",
    "de": "German",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "ru": "Russian",
}


class CosyEngine(TTSEngine):
    id = "cosyvoice"
    name = "CosyVoice 3 (CPU)"
    description = "FunAudioLLM 다국어 모델. 참조 음색으로 한국어를 읽는다(cross-lingual). CPU 사이드카."
    license = "Apache-2.0 (코드·가중치 모두)"
    supports_voice_cloning = True

    _SAMPLE_RATE = 24000

    def __init__(self) -> None:
        self._worker: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def status(self) -> EngineStatus:
        if not COSY_PYTHON.exists():
            return EngineStatus(False, f"사이드카 venv 없음 — scripts/setup-cosy.sh ({COSY_PYTHON})")
        if not (COSY_REPO / "cosyvoice" / "cli" / "cosyvoice.py").exists():
            return EngineStatus(False, f"CosyVoice repo 없음: {COSY_REPO}")
        if not _cosy_installed():
            return EngineStatus(
                False, "venv 에 cosyvoice 의존성이 없음 — scripts/setup-cosy.sh 를 다시 실행하세요"
            )
        return EngineStatus(True, "준비됨 (CPU 사이드카)", "cpu")

    def languages(self) -> dict[str, str]:
        return dict(_LANGUAGES)

    def sample_rate(self) -> int:
        return self._SAMPLE_RATE

    def _ensure_worker(self) -> subprocess.Popen:
        if self._worker is not None and self._worker.poll() is None:
            return self._worker
        env = {**os.environ, "COSYVOICE_REPO": str(COSY_REPO)}
        env.setdefault("HF_HOME", os.environ.get("VOICEREC_MODELS_DIR", str(_REPO_ROOT / "var" / "models")))
        self._worker = subprocess.Popen(
            [str(COSY_PYTHON), str(COSY_WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=env,
        )
        return self._worker

    def synthesize(self, request: SynthesisRequest, out_wav: Path) -> float:
        status = self.status()
        if not status.available:
            raise RuntimeError(status.detail)

        out_wav.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "text": request.text,
                "out": str(out_wav),
                "prompt_wav": str(request.voice_path) if request.voice_path else None,
                # 전사가 있으면 워커가 화자 고정(add_zero_shot_spk)으로 씬 간 톤을 맞춘다.
                "prompt_text": request.prompt_text or None,
            },
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
                raise RuntimeError(f"CosyVoice 워커가 죽었습니다: {exc}") from exc

        if not line:
            self._worker = None
            raise RuntimeError("CosyVoice 워커가 응답 없이 종료됐습니다 (모델 로딩 실패일 수 있음)")
        response = json.loads(line)
        if not response.get("ok"):
            raise RuntimeError(f"CosyVoice 합성 실패: {response.get('error')}")
        return probe_duration(out_wav)


def _cosy_installed() -> bool:
    """사이드카 venv 에 cosyvoice 핵심 의존성이 있는지 (import 하지 않고 파일로 확인)."""
    site = list(COSY_PYTHON.parent.parent.glob("lib/python*/site-packages"))
    return bool(site) and (site[0] / "hyperpyyaml").exists()
