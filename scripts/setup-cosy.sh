#!/usr/bin/env bash
# (선택) CosyVoice 3 CPU 사이드카를 설치한다.
#
# 왜 별도 venv 인가: CosyVoice 는 torch==2.3.1(cu121) 을 핀해 메인 venv(torch 2.13/cu130)와
# 공존이 불가능하다. cu121 휠에는 RTX 50 시리즈(sm_120) 커널이 없어 GPU 도 못 쓰므로 CPU 로 돈다.
# 코드는 공식 GitHub repo(Apache-2.0)를 clone 해서 PYTHONPATH 로 쓴다 — PyPI 의 cosyvoice 패키지는
# GPL-3.0 이라 쓰지 않는다.
#
# 없어도 앱은 돈다 — Chatterbox/MeloTTS 로 폴백한다.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${VOICEREC_COSY_PYTHON_BIN:-python3.10}"
REPO_DIR="$ROOT_DIR/vendor/CosyVoice"
MODELS_DIR="${VOICEREC_MODELS_DIR:-$ROOT_DIR/var/models}"

command -v "$PYTHON_BIN" >/dev/null 2>&1 || { echo "✗ $PYTHON_BIN 없음 (CosyVoice 는 3.10 권장)"; exit 1; }

# ── 1. repo (Apache-2.0, Matcha submodule 포함) ──────────────────────────────
if [ ! -d "$REPO_DIR/cosyvoice" ]; then
  echo "→ CosyVoice repo clone"
  git clone --depth 1 --recursive https://github.com/FunAudioLLM/CosyVoice.git "$REPO_DIR"
else
  echo "· repo 있음: $REPO_DIR"
fi

# ── 2. 사이드카 venv (CPU) ───────────────────────────────────────────────────
if command -v uv >/dev/null 2>&1; then
  uv venv --python "$PYTHON_BIN" backend/.venv-cosy
  PIP=(env "VIRTUAL_ENV=$ROOT_DIR/backend/.venv-cosy" uv pip install)
else
  "$PYTHON_BIN" -m venv backend/.venv-cosy
  PIP=(backend/.venv-cosy/bin/pip install)
  backend/.venv-cosy/bin/pip install --upgrade pip
fi

echo "→ torch 2.3.1 (CPU)"
"${PIP[@]}" torch==2.3.1 torchaudio==2.3.1 --index-url https://download.pytorch.org/whl/cpu

# requirements.txt 전체가 아니라 추론에 필요한 것만 (deepspeed/tensorrt/gradio/grpc/fastapi 등
# 학습·GPU가속·서빙용은 제외 — CosyVoice 코드가 optional import 로 처리한다).
echo "→ CosyVoice 추론 의존성"
"${PIP[@]}" \
  conformer==0.3.2 diffusers==0.29.0 hydra-core==1.3.2 HyperPyYAML==1.2.3 \
  "librosa==0.10.2" lightning==2.2.4 omegaconf==2.3.0 onnx==1.16.0 onnxruntime==1.18.0 \
  transformers==4.51.3 wetext==0.0.4 soundfile "numpy==1.26.4" inflect==7.3.1 \
  x-transformers==2.11.24 pyworld==0.3.4 networkx==3.1 gdown rich \
  "matplotlib==3.7.5" wget==3.2 "pyarrow==18.1.0" "protobuf==4.25" "tensorboard==2.14.0"
# openai-whisper 는 speech tokenizer 가 쓴다. pkg_resources 를 빌드에 요구해 setuptools 핀 + no-build-isolation 이 필요하다.
"${PIP[@]}" "setuptools<81"
"${PIP[@]}" --no-build-isolation openai-whisper==20231117

# ── 3. 가중치 (Apache-2.0) ───────────────────────────────────────────────────
echo "→ Fun-CosyVoice3-0.5B 가중치 (~2GB)"
HF_HOME="$MODELS_DIR" backend/.venv-cosy/bin/python - <<'PY'
from huggingface_hub import snapshot_download
p = snapshot_download("FunAudioLLM/Fun-CosyVoice3-0.5B-2512")
print("  ✓", p)
PY

echo
echo "✓ CosyVoice 3 사이드카 설치 완료."
echo "  스모크: 아래 한 줄로 확인"
echo "    COSYVOICE_REPO=$REPO_DIR HF_HOME=$MODELS_DIR backend/.venv-cosy/bin/python \\"
echo "      -c \"import json,subprocess\" # (또는 앱에서 엔진 'cosyvoice' 선택)"
