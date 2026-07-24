# wav 의 기본주파수(F0) 중앙값을 재서 목소리 음역을 가늠한다 (남성 85~180Hz / 여성 165~255Hz)

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np


def median_f0(path: Path, fmin: float = 70.0, fmax: float = 350.0) -> tuple[float, float]:
    """자기상관으로 프레임별 F0 를 추정해 (중앙값, 유성음 비율) 을 돌려준다."""
    with wave.open(str(path), "rb") as fh:
        rate = fh.getframerate()
        channels = fh.getnchannels()
        raw = fh.readframes(fh.getnframes())

    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)

    frame = int(0.04 * rate)          # 40ms
    hop = int(0.02 * rate)            # 20ms
    lag_min, lag_max = int(rate / fmax), int(rate / fmin)

    pitches: list[float] = []
    voiced = 0
    total = 0
    for start in range(0, len(samples) - frame, hop):
        window = samples[start : start + frame]
        if np.sqrt(np.mean(window**2)) < 0.02:   # 무음/숨소리는 건너뛴다
            continue
        total += 1
        window = window - window.mean()
        corr = np.correlate(window, window, mode="full")[frame - 1 :]
        if corr[0] <= 0:
            continue
        segment = corr[lag_min:lag_max]
        if segment.size == 0:
            continue
        lag = int(np.argmax(segment)) + lag_min
        # 자기상관 정점이 충분히 뚜렷할 때만 유성음으로 본다
        if corr[lag] / corr[0] > 0.3:
            pitches.append(rate / lag)
            voiced += 1

    if not pitches:
        return 0.0, 0.0
    return float(np.median(pitches)), voiced / max(total, 1)


def main() -> int:
    for arg in sys.argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f"  {path.name}: 없음")
            continue
        f0, ratio = median_f0(path)
        if f0 == 0:
            label = "측정 불가"
        elif f0 < 155:
            label = "남성 음역"
        elif f0 < 190:
            label = "경계 (낮은 여성 / 높은 남성)"
        else:
            label = "여성 음역"
        print(f"  {path.name:<42} F0 중앙값 {f0:6.1f} Hz  유성 {ratio:4.0%}  → {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
