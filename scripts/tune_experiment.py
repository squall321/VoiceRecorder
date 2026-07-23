# 자연스러움 개선 실험 — 파라미터 조합과 "MeloTTS 출력을 참조 음성으로" 기법을 비교 생성한다

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.textnorm import normalize  # noqa: E402
from app.tts import SynthesisRequest, get_engine  # noqa: E402

OUT = ROOT / "var" / "tune"

SCENES = {
    "01오프닝": "질문 하나가 의사결정문이 되기까지 — HWAX 협업진단 플랫폼. 방열 난제를 맡은 B책임의 하루를 따라가 봅니다.",
    "06자체교정": "토론이 시작됩니다. '그라파이트 시트로 충분하다'던 초기 계산 — 2라운드에서 다른 전문가가 핫스팟 열유속 누락을 지적하며 판정이 뒤집힙니다. 틀린 계산도 토론이 스스로 잡아냅니다. 결론은 6인 만장일치, 대안 B.",
}

DICT = [("HWAX", "하드웨어 에이엑스")]

# (이름, exaggeration, cfg_weight, temperature)
PRESETS = [
    ("A_기본", 0.5, 0.5, 0.8),
    ("B_차분", 0.35, 0.3, 0.7),
    ("C_평탄", 0.25, 0.2, 0.6),
    ("D_또박", 0.4, 0.7, 0.65),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    chatterbox = get_engine("chatterbox")
    melo = get_engine("melo")

    for label, raw in SCENES.items():
        text = normalize(raw, dictionary=DICT, read_numbers=True)
        print(f"\n=== {label} ===\n{text}\n")

        # 1) MeloTTS 로 한국어 프로소디 참조본을 만든다 (MIT, 한국어 학습 모델)
        ref = OUT / f"_ref_{label}.wav"
        if melo.status().available:
            t0 = time.time()
            melo.synthesize(SynthesisRequest(text=text, language="ko"), ref)
            print(f"  참조본(MeloTTS) {time.time() - t0:.1f}s")
            shutil.copyfile(ref, OUT / f"{label}__E_MeloTTS단독.wav")

        # 2) 파라미터 프리셋 × (참조 음성 없음 / MeloTTS 참조)
        for name, exag, cfg, temp in PRESETS:
            for use_ref in (False, True):
                if use_ref and not ref.exists():
                    continue
                suffix = "참조있음" if use_ref else "참조없음"
                dst = OUT / f"{label}__{name}_{suffix}.wav"
                t0 = time.time()
                duration = chatterbox.synthesize(
                    SynthesisRequest(
                        text=text,
                        language="ko",
                        voice_path=ref if use_ref else None,
                        exaggeration=exag,
                        cfg_weight=cfg,
                        temperature=temp,
                    ),
                    dst,
                )
                print(f"  {name:<8} {suffix}  {duration:5.2f}s  ({time.time() - t0:.1f}s)")

        ref.unlink(missing_ok=True)

    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
