# CosyVoice3 instruct2 모드가 한국어 스타일 지시를 따르는지 확인 (한 음색에서 톤 변주)

from __future__ import annotations

import os
import sys
import wave
from pathlib import Path

REPO = Path(os.environ["COSYVOICE_REPO"])
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "third_party" / "Matcha-TTS"))

PROMPT = sys.argv[1]  # 참조 음성 경로
OUTDIR = Path(sys.argv[2])
SAMPLE = "복잡한 해석 업무, 이제 대화로 지시하는 시대입니다."
STYLES = [
    ("bright", "You are a helpful assistant. 밝고 활기차게 말해줘.<|endofprompt|>"),
    ("calm", "You are a helpful assistant. 아주 차분하고 느리게 말해줘.<|endofprompt|>"),
    ("news", "You are a helpful assistant. 뉴스 앵커처럼 또박또박 말해줘.<|endofprompt|>"),
]


def save(path, audio, sr):
    import numpy as np

    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sr)
        fh.writeframes(pcm)


def main() -> int:
    import torch
    from huggingface_hub import snapshot_download
    from cosyvoice.cli.cosyvoice import CosyVoice3

    m = CosyVoice3(snapshot_download("FunAudioLLM/Fun-CosyVoice3-0.5B-2512"),
                   load_trt=False, load_vllm=False, fp16=False)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    for name, instruct in STYLES:
        try:
            pieces = []
            for o in m.inference_instruct2(SAMPLE, instruct, PROMPT, stream=False):
                pieces.append(o["tts_speech"])
            audio = torch.cat(pieces, dim=1).reshape(-1).cpu().numpy()
            save(OUTDIR / f"instruct_{name}.wav", audio, int(m.sample_rate))
            print(f"  {name}: OK {audio.shape[0] / m.sample_rate:.2f}s", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  {name}: FAIL {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
