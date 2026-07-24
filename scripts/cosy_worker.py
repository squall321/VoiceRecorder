# CosyVoice3 사이드카 venv(.venv-cosy) 안에서 도는 상주 합성 워커
#
# CosyVoice 는 pip 패키지가 아니라 repo 를 PYTHONPATH 에 얹어 쓴다 (공식 GitHub, Apache-2.0).
# torch 2.3.1(cu121) 을 핀해 메인 venv(torch 2.13/cu130)와 공존 불가라 별도 venv 에서 subprocess 로만 부른다.
# 프로토콜(melo_worker 와 동일): stdin JSON 한 줄 → stdout {"ok":..} 한 줄. 프로세스는 살아 있는다.
#   요청: {"text":.., "out":"/path.wav", "prompt_wav":"/ref.wav"|null, "prompt_text":".."|null}
#
# 화자 일관성(핵심): prompt_text 가 함께 오면 add_zero_shot_spk 로 화자 임베딩을 한 번만 추출해
# 고정하고(같은 prompt_wav 는 캐시), 이후 전 씬이 그 고정 임베딩을 재사용한다(inference_zero_shot).
# 이러면 "한 사람이 쭉 읽는" 느낌 — 씬마다 프롬프트를 새로 해석하며 톤이 튀던 문제가 줄어든다.
# prompt_text 가 없으면 cross-lingual 폴백(음색만 참조, 씬 간 변동 큼).

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(os.environ["COSYVOICE_REPO"])
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "third_party" / "Matcha-TTS"))

_MODEL = None
_DEFAULT_PROMPT = REPO / "asset" / "cross_lingual_prompt.wav"
_SYS = "You are a helpful assistant.<|endofprompt|>"
_SPK_CACHE: set[str] = set()  # 이미 등록한 (prompt_wav, prompt_text) 지문


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


def _register_speaker(model, prompt_path: str, prompt_text: str) -> str:
    """프롬프트에서 화자 임베딩을 한 번만 추출해 고정하고 화자 id 를 돌려준다 (캐시)."""
    spk_id = "spk_" + hashlib.sha1(f"{prompt_path}|{prompt_text}".encode()).hexdigest()[:12]
    if spk_id not in _SPK_CACHE:
        model.add_zero_shot_spk(_SYS + prompt_text, prompt_path, spk_id)
        _SPK_CACHE.add(spk_id)
    return spk_id


def _synthesize(request: dict) -> dict:
    import numpy as np
    import torch

    model = _load_model()
    # CosyVoice3 frontend 는 prompt_wav 를 파일 경로로 받아 내부에서 load_wav 한다 (CosyVoice2 는 tensor).
    prompt_path = request.get("prompt_wav") or str(_DEFAULT_PROMPT)
    prompt_text = (request.get("prompt_text") or "").strip()

    instruct = (request.get("instruct") or "").strip()

    pieces = []
    if instruct:
        # instruct 모드 — 스타일 지시(밝게/차분하게/뉴스풍 등)로 톤을 바꾼다. 같은 음색에서 변주.
        instruct_text = "You are a helpful assistant. " + instruct + "<|endofprompt|>"
        for out in model.inference_instruct2(
            request["text"], instruct_text, prompt_path, stream=False, speed=1.0
        ):
            pieces.append(out["tts_speech"])
    elif prompt_text:
        # 화자 고정 경로 — 임베딩 재사용으로 씬 간 톤 일관성 확보.
        spk_id = _register_speaker(model, prompt_path, prompt_text)
        for out in model.inference_zero_shot(
            request["text"], "", "", zero_shot_spk_id=spk_id, stream=False, speed=1.0
        ):
            pieces.append(out["tts_speech"])
    else:
        # 폴백 — prompt_text 가 없으면 cross-lingual (음색만, 씬 간 변동 큼).
        # CosyVoice3 는 텍스트 앞에 시스템 프롬프트 + <|endofprompt|> 가 필수다.
        text = _SYS + request["text"]
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
