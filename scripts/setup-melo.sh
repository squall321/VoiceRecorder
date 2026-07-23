#!/usr/bin/env bash
# (선택) MeloTTS CPU 사이드카를 별도 venv 에 설치한다.
#
# 왜 별도 venv 인가: MeloTTS 는 torch<2.0, transformers==4.27.4, librosa==0.9.1 을 핀하고
# Chatterbox 는 torch>=2.6, transformers==5.2.0 을 요구한다. 한 venv 에 공존이 불가능하다.
# 여기 설치하면 앱이 subprocess 로만 호출하므로 메인 venv 는 그대로다.
#
# 없어도 앱은 돈다 — Chatterbox 가 GPU 없거나 VRAM 이 모자라면 CPU 로 폴백한다.
# 이건 "CPU 에서 훨씬 빠른 대안"이 필요할 때만 설치한다.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/backend"

PYTHON_BIN="${VOICEREC_MELO_PYTHON_BIN:-python3.10}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
  echo "✗ $PYTHON_BIN 이 없습니다. MeloTTS 는 오래된 의존성을 핀해서 3.10 이 가장 안전합니다."
  exit 1
}

"$PYTHON_BIN" -m venv .venv-melo
.venv-melo/bin/pip install --upgrade pip
.venv-melo/bin/pip install git+https://github.com/myshell-ai/MeloTTS.git
.venv-melo/bin/python -m unidic download

echo
echo "✓ MeloTTS 사이드카 설치 완료: $PWD/.venv-melo"
echo "  확인: echo '{\"text\":\"안녕하세요\",\"language\":\"KR\",\"out\":\"/tmp/melo.wav\"}' | .venv-melo/bin/python ../scripts/melo_worker.py"
