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

# librosa 0.9.1 이 pkg_resources 를 쓰는데 setuptools 81+ 가 그걸 제거했다.
# 핀을 안 걸면 합성 시점에 ModuleNotFoundError: pkg_resources 로 죽는다.
.venv-melo/bin/pip install "setuptools<81"
# 한국어 g2p 가 런타임에 설치를 시도하므로 미리 넣어 둔다 (폐쇄망 대비).
.venv-melo/bin/pip install python-mecab-ko || echo "  ⚠ python-mecab-ko 설치 실패 — 런타임 자동 설치에 의존"

# MeloTTS 한국어는 부속 BERT(kykim/bert-kor-base 등)를 런타임에 받는다.
# 앱이 보는 모델 경로에 미리 캐시해 둬야 HF_HUB_OFFLINE=1 에서 동작한다.
MODELS_DIR="${VOICEREC_MODELS_DIR:-$ROOT_DIR/var/models}"
echo "→ MeloTTS 부속 모델 캐시 ($MODELS_DIR)"
echo '{"text":"캐시 준비용 문장입니다.","language":"KR","out":"/tmp/_melo_warmup.wav"}' \
  | HF_HOME="$MODELS_DIR" .venv-melo/bin/python "$ROOT_DIR/scripts/melo_worker.py" >/dev/null 2>&1 \
  && rm -f /tmp/_melo_warmup.wav && echo "  ✓ 캐시 완료" \
  || echo "  ⚠ 캐시 실패 — 온라인 상태에서 다시 실행하세요"

echo
echo "✓ MeloTTS 사이드카 설치 완료: $PWD/.venv-melo"
echo "  확인: echo '{\"text\":\"안녕하세요\",\"language\":\"KR\",\"out\":\"/tmp/melo.wav\"}' | .venv-melo/bin/python ../scripts/melo_worker.py"
