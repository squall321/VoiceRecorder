# Chatterbox Multilingual (Resemble AI, MIT) 엔진 — 한국어 포함 23개 언어, GPU/CPU 자동 선택

from __future__ import annotations

import importlib.util
import os
import threading
from pathlib import Path

from .. import config
from ..script_parser import chunk_text
from .base import EngineStatus, SynthesisRequest, TTSEngine

# HF 캐시를 DATA_DIR 밑으로 고정한다. import 전에 잡아야 huggingface_hub 가 읽는다.
os.environ.setdefault("HF_HOME", str(config.MODELS_DIR))


class ChatterboxEngine(TTSEngine):
    id = "chatterbox"
    name = "Chatterbox Multilingual"
    description = "Resemble AI 다국어 모델. 참조 음성 3~10초로 화자를 복제할 수 있다."
    license = "MIT (코드·가중치 모두)"
    supports_voice_cloning = True

    _SAMPLE_RATE_FALLBACK = 24000

    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()
        self._device: str | None = None
        # GPU 를 다른 프로세스와 나눠 쓰는 서버가 있어 VRAM 부족으로 CPU 로 내려간 사실을
        # 상태에 남긴다 (조용히 느려지면 원인을 못 찾는다).
        self._fallback_note: str | None = None

    # ── 상태 ────────────────────────────────────────────────────────────────

    def _resolve_device(self) -> str:
        forced = os.environ.get("VOICEREC_DEVICE")
        if forced:
            return forced
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def status(self) -> EngineStatus:
        if importlib.util.find_spec("chatterbox") is None:
            return EngineStatus(False, "chatterbox-tts 가 설치되지 않았습니다 (scripts/setup-backend.sh)")
        if importlib.util.find_spec("torch") is None:
            return EngineStatus(False, "torch 가 설치되지 않았습니다")

        device = self._device or self._resolve_device()
        detail = f"준비됨 ({device})"
        if device == "cuda":
            try:
                import torch

                name = torch.cuda.get_device_name(0)
                capability = "sm_%d%d" % torch.cuda.get_device_capability(0)
                # torch 휠에 이 GPU 아키텍처 커널이 없으면 첫 커널 실행에서 죽는다.
                # 미리 잡아내 "왜 안 되는지"를 UI 에 그대로 보여준다.
                if capability not in torch.cuda.get_arch_list():
                    return EngineStatus(
                        False,
                        f"{name} ({capability})용 커널이 없는 torch {torch.__version__} 입니다. "
                        f"지원: {', '.join(torch.cuda.get_arch_list())}",
                        device,
                    )
                free_bytes, total_bytes = torch.cuda.mem_get_info()
                detail = f"준비됨 ({name}, VRAM {free_bytes / 2**30:.1f}/{total_bytes / 2**30:.1f} GB 여유)"
            except Exception as exc:  # noqa: BLE001 - 상태 조회는 실패해도 넘어간다
                detail = f"준비됨 (cuda, 정보 조회 실패: {exc})"
        if self._fallback_note:
            detail += f" · {self._fallback_note}"
        if self._model is None:
            detail += " · 첫 합성 시 모델 로딩"
        return EngineStatus(True, detail, device)

    def languages(self) -> dict[str, str]:
        try:
            from chatterbox.mtl_tts import SUPPORTED_LANGUAGES

            return dict(SUPPORTED_LANGUAGES)
        except ImportError:
            return {"ko": "Korean"}

    def sample_rate(self) -> int:
        if self._model is not None:
            return int(self._model.sr)
        return self._SAMPLE_RATE_FALLBACK

    # ── 모델 ────────────────────────────────────────────────────────────────

    def _load(self, device: str):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        model = ChatterboxMultilingualTTS.from_pretrained(device=device)
        self._device = device
        return model

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                device = self._resolve_device()
                try:
                    self._model = self._load(device)
                except Exception as exc:  # noqa: BLE001
                    # 이 서버의 GPU 는 다른 서비스와 공유된다. VRAM 이 모자라면 조용히 죽는 대신
                    # CPU 로 내려가서 (느리더라도) 결과는 나오게 한다.
                    if device == "cuda" and _is_oom(exc):
                        _release_cuda()
                        self._fallback_note = "VRAM 부족으로 CPU 로 전환됨"
                        self._model = self._load("cpu")
                    else:
                        raise
        return self._model

    def warmup(self) -> None:
        self._ensure_model()

    # ── 합성 ────────────────────────────────────────────────────────────────

    def synthesize(self, request: SynthesisRequest, out_wav: Path) -> float:
        model = self._ensure_model()
        chunks = chunk_text(request.text, config.MAX_CHARS_PER_CHUNK)
        if not chunks:
            raise ValueError("합성할 텍스트가 비어 있습니다")

        with self._lock:  # GPU 1장 — 동시 합성은 VRAM 만 먹고 전체 시간은 안 준다
            try:
                frames, sample_rate = self._render(model, chunks, request)
            except Exception as exc:  # noqa: BLE001
                if self._device == "cuda" and _is_oom(exc):
                    self._model = None
                    _release_cuda()
                    self._fallback_note = "합성 중 VRAM 부족 — CPU 로 전환됨"
                    self._model = self._load("cpu")
                    frames, sample_rate = self._render(self._model, chunks, request)
                else:
                    raise

        from .. import audio as audio_utils

        return audio_utils.write_wav_frames(out_wav, frames, sample_rate)

    def _render(self, model, chunks: list[str], request: SynthesisRequest) -> tuple[bytes, int]:
        """청크별로 합성해 16bit PCM 프레임 하나로 이어 붙인다."""
        import numpy as np

        prompt = str(request.voice_path) if request.voice_path else None
        sample_rate = int(model.sr)
        gap = np.zeros(int(config.CHUNK_GAP_SEC * sample_rate), dtype=np.float32)

        pieces: list["np.ndarray"] = []
        for position, chunk in enumerate(chunks):
            wav = model.generate(
                chunk,
                language_id=request.language,
                audio_prompt_path=prompt,
                exaggeration=request.exaggeration,
                cfg_weight=request.cfg_weight,
                temperature=request.temperature,
            )
            samples = wav.detach().cpu().numpy().reshape(-1).astype(np.float32)
            if position and gap.size:
                pieces.append(gap)
            pieces.append(samples)

        audio = np.concatenate(pieces) if len(pieces) > 1 else pieces[0]
        pcm = np.clip(audio, -1.0, 1.0) * 32767.0
        return pcm.astype("<i2").tobytes(), sample_rate


def _is_oom(exc: BaseException) -> bool:
    return "out of memory" in str(exc).lower() or type(exc).__name__ == "OutOfMemoryError"


def _release_cuda() -> None:
    try:
        import gc

        import torch

        gc.collect()
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001 - 정리 실패는 무시해도 된다
        pass
