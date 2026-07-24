# add_zero_shot_spk(화자 임베딩 고정) 방식이 씬 간 일관성을 높이는지 검증하는 일회성 스크립트

from __future__ import annotations

import json
import os
import sys
import wave
from pathlib import Path

REPO = Path(os.environ["COSYVOICE_REPO"])
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "third_party" / "Matcha-TTS"))

CFG = json.load(open(sys.argv[1], encoding="utf-8"))
OUT = Path(sys.argv[2])
SYS = "You are a helpful assistant.<|endofprompt|>"


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

    # 화자 등록: 프롬프트 음성 + 그 음성의 텍스트로 임베딩을 한 번 추출해 고정한다.
    m.add_zero_shot_spk(SYS + CFG["prompt_text"], CFG["calm_raw"], "narrator")

    for t in CFG["targets"]:
        pieces = []
        # 등록된 화자로 합성 — prompt_wav 를 매번 처리하지 않고 고정 임베딩 재사용.
        for o in m.inference_zero_shot(t["text"], "", "", zero_shot_spk_id="narrator", stream=False):
            pieces.append(o["tts_speech"])
        audio = torch.cat(pieces, dim=1).reshape(-1).cpu().numpy()
        save(OUT / f"spk_{t['n']}.wav", audio, int(m.sample_rate))
        print(f"  씬{t['n']} OK · {audio.shape[0] / m.sample_rate:.2f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
