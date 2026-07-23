#!/usr/bin/env bash
# 백엔드 venv 를 만든다. 설치 순서가 중요하다 — 아래 주석 참고.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/backend"

PYTHON_BIN="${VOICEREC_PYTHON:-python3.12}"
TORCH_INDEX="${VOICEREC_TORCH_INDEX:-https://download.pytorch.org/whl/cu130}"

command -v "$PYTHON_BIN" >/dev/null 2>&1 || { echo "✗ $PYTHON_BIN 이 없습니다"; exit 1; }

if command -v uv >/dev/null 2>&1; then
  PIP=(uv pip install)
  uv venv --python "$PYTHON_BIN" .venv
  export VIRTUAL_ENV="$PWD/.venv"
else
  PIP=(.venv/bin/pip install)
  "$PYTHON_BIN" -m venv .venv
  .venv/bin/pip install --upgrade pip
fi

# ── 1. torch 를 먼저, 그리고 이 GPU 를 지원하는 빌드로 ─────────────────────────
# chatterbox-tts 는 torch==2.6.0 을 핀하는데 그 휠에는 sm_120(Blackwell, RTX 50 시리즈)
# 커널이 없다. 그대로 두면 import 도 되고 cuda.is_available() 도 True 인데 첫 커널 실행에서
# "no kernel image is available for execution on the device" 로 죽는다.
echo "→ torch/torchaudio ($TORCH_INDEX)"
"${PIP[@]}" --index-url "$TORCH_INDEX" torch torchaudio

# ── 2. chatterbox 는 의존성 없이 ────────────────────────────────────────────
# --no-deps 를 빼면 pip 가 torch 를 2.6.0 으로 되돌려 1단계를 무효로 만든다.
echo "→ chatterbox-tts (--no-deps)"
"${PIP[@]}" --no-deps "chatterbox-tts==0.1.7"

# ── 3. chatterbox 가 실제로 쓰는 의존성만 (gradio 는 데모 UI 라 제외) ────────
echo "→ chatterbox 런타임 의존성"
"${PIP[@]}" \
  "numpy<2" \
  "librosa==0.11.0" \
  s3tokenizer \
  "transformers==5.2.0" \
  "diffusers==0.29.0" \
  "resemble-perth>=1.0.0" \
  "conformer==0.3.2" \
  "safetensors==0.5.3" \
  spacy-pkuseg \
  "pykakasi==2.3.0" \
  pyloudnorm \
  omegaconf

# ── 4. 앱 본체 ──────────────────────────────────────────────────────────────
echo "→ voicerecorder-backend"
"${PIP[@]}" -e ".[dev]"

echo
echo "✓ 설치 완료. 확인:"
.venv/bin/python - <<'PY'
import torch
print(f"  torch {torch.__version__} · cuda={torch.cuda.is_available()}")
if torch.cuda.is_available():
    cap = "sm_%d%d" % torch.cuda.get_device_capability(0)
    ok = "OK" if cap in torch.cuda.get_arch_list() else "✗ 이 torch 빌드는 이 GPU 를 지원하지 않음"
    print(f"  {torch.cuda.get_device_name(0)} ({cap}) → {ok}")
PY
echo
echo "  모델 받기:   scripts/fetch-models.sh"
echo "  스모크 테스트: backend/.venv/bin/python scripts/smoke_chatterbox.py"
echo "  테스트:      cd backend && .venv/bin/python -m pytest"
