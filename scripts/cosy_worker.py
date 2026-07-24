# CosyVoice3 사이드카 venv(.venv-cosy) 안에서 도는 상주 합성 워커
#
# CosyVoice 는 pip 패키지가 아니라 repo 를 PYTHONPATH 에 얹어 쓴다 (공식 GitHub, Apache-2.0).
# torch 2.3.1(cu121) 을 핀해 메인 venv(torch 2.13/cu130)와 공존 불가라 별도 venv 에서 subprocess 로만 부른다.
# 프로토콜(melo_worker 와 동일): stdin JSON 한 줄 → stdout {"ok":..} 한 줄. 프로세스는 살아 있는다.
#   요청: {"text":.., "out":"/path.wav", "prompt_wav":"/ref.wav"|null}
# 참조 음성(prompt_wav)이 없으면 repo asset 의 기본 프롬프트를 쓴다 (cross-lingual: 음색만 참조, 언어는 타깃).

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(os.environ["COSYVOICE_REPO"])
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "third_party" / "Matcha-TTS"))

_MODEL = None
_DEFAULT_PROMPT = REPO / "asset" / "cross_lingual_prompt.wav"


def _load_model():
    global _MODEL
    if _MODEL is None:
        from huggingface_hub import snapshot_download
        from cosyvoice.cli.cosyvoice import CosyVoice3

        model_dir = snapshot_download("FunAudioLLM/Fun-CosyVoice3-0.5B-2512")
        # CPU 사이드카 — torch 2.3.1(cu121) 은 RTX 50 시리즈(sm_120) 커널이 없어 GPU 를 못 쓴다.
        # CosyVoice3 는 load_trt/load_vllm 만 받는다 (load_jit 없음).
        _MODEL = CosyVoice3(model_dir, load_trt=False, load_vllm=False, fp16=False)
    return _MODEL


def _synthesize(request: dict) -> dict:
    import numpy as np
    import torch

    model = _load_model()
    # CosyVoice3 frontend 는 prompt_wav 를 파일 경로로 받아 내부에서 load_wav 한다 (CosyVoice2 는 tensor).
    prompt_path = request.get("prompt_wav") or str(_DEFAULT_PROMPT)

    # CosyVoice3 는 Qwen LLM 기반이라 텍스트 앞에 시스템 프롬프트 + <|endofprompt|> 가 필수다
    # (example.py 참고). 없으면 AssertionError 로 죽는다.
    text = "You are a helpful assistant.<|endofprompt|>" + request["text"]

    # cross_lingual: 프롬프트 음색으로 타깃 텍스트(한국어)를 읽는다. prompt_text 불필요.
    pieces = []
    for out in model.inference_cross_lingual(text, prompt_path, stream=False, speed=1.0):
        pieces.append(out["tts_speech"])
    if not pieces:
        raise RuntimeError("빈 합성 결과")
    audio = torch.cat(pieces, dim=1).reshape(-1).cpu().numpy()

    import wave

    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    out_path = request["out"]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(out_path, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(int(model.sample_rate))
        fh.writeframes(pcm)
    return {"ok": True, "out": out_path, "sr": int(model.sample_rate)}


def main() -> int:
    real_stdout = sys.stdout
    sys.stdout = sys.stderr  # 모델 로딩 로그가 프로토콜(stdout)을 오염시키지 않게

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            response = _synthesize(json.loads(line))
        except Exception as exc:  # noqa: BLE001 - 실패해도 워커는 살아 있어야 한다
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(response, ensure_ascii=False), file=real_stdout, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
