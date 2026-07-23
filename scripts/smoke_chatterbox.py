# 앱의 실제 합성 경로(ChatterboxEngine)로 한국어 wav 가 나오는지 확인하는 스모크

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.textnorm import normalize  # noqa: E402
from app.tts import SynthesisRequest, get_engine  # noqa: E402

RAW = (
    '01 오프닝 (0:00–0:08) "질문 하나가 의사결정문이 되기까지 — HWAX 협업진단 플랫폼. '
    '방열 난제를 맡은 B책임의 하루를 따라가 봅니다."'
)


def main() -> int:
    from app.script_parser import parse_script

    parsed = parse_script(RAW)
    if not parsed.scenes:
        print("✗ 파싱 실패")
        return 1
    scene = parsed.scenes[0]
    print(f"파싱: #{scene.number} {scene.title!r} 목표 {scene.target_duration_sec}s")

    text = normalize(scene.text, dictionary=[("HWAX", "에이치왁스")], read_numbers=True)
    print(f"정규화: {text}")

    engine = get_engine("chatterbox")
    status = engine.status()
    print(f"엔진: {status.available} · {status.detail}")
    if not status.available:
        return 1

    out = ROOT / "var" / "smoke_ko.wav"
    t0 = time.time()
    duration = engine.synthesize(SynthesisRequest(text=text, language="ko"), out)
    elapsed = time.time() - t0

    print(f"합성: {elapsed:.1f}s → {duration:.2f}s 오디오 (RTF {elapsed / duration:.2f})")
    print(f"저장: {out} ({out.stat().st_size} bytes), device={engine.status().device}")
    return 0 if duration > 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
