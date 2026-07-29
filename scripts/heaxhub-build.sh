#!/usr/bin/env bash
# HEAXHub SIF 빌드 훅 — fastapi_react.def Stage3 가 `pip install -e .` 뒤에 호출한다.
# pyproject 밖으로 뺀 TTS 스택 3종을 컨테이너에 심는다. 세 엔진은 torch 버전이 서로
# 충돌(Chatterbox torch≥2.6 / MeloTTS torch<2.0 / CosyVoice torch 2.3.1)해 한 파이썬에
# 공존이 불가능하므로, 개발용 setup-*.sh 와 같은 격리 구조를 컨테이너 안에 그대로 재현한다.
#   1) 컨테이너 system python(3.12): torch + Chatterbox
#   2) /app/backend/.venv-melo  (uv 로 받은 python 3.10): MeloTTS
#   3) /app/backend/.venv-cosy  (uv 로 받은 python 3.10): CosyVoice3 + /app/vendor/CosyVoice repo
#
# **가중치는 SIF 에 넣지 않는다.** 모델 캐시는 런타임 볼륨 /data/models(=VOICEREC_MODELS_DIR,
# HF_HOME)를 scripts/models-from-drive.sh 가 채운다. 이 훅은 "코드·의존성·사전"만 심는다.
#
# torch 기본은 GPU(cu130, sm_120/RTX50). 런처가 resources.gpu+호스트GPU 판정 후 --nv 를 켜면
# Chatterbox 가 GPU 로 돈다(없으면 CUDA 미탐지 → CPU 폴백). 다른 GPU 세대면 빌드 시
# VOICEREC_TORCH_INDEX 로 맞는 인덱스를 준다(예: .../whl/cu121). CPU 전용이면 .../whl/cpu.
#
# 주의: 이 훅은 빌드 시점에 pytorch.org/PyPI/GitHub 에 닿아야 한다(수 GB) → **온라인 박스에서
# fat SIF 를 빌드**하고 dist-to-drive(per-app SIF)로 폐쇄망 서버에 나른다. 폐쇄망 직접 빌드는
# torch/휠을 사내 미러(BUILD_PIP_*)에 넣어야 한다.
set -euo pipefail

export PIP_ROOT_USER_ACTION=ignore
export PIP_DISABLE_PIP_VERSION_CHECK=1
export DEBIAN_FRONTEND=noninteractive

TORCH_INDEX="${VOICEREC_TORCH_INDEX:-https://download.pytorch.org/whl/cu130}"
# uv 가 받는 사이드카용 python 3.10 을 예측 가능한(=SIF 에 확실히 구워지는) 경로에 둔다.
export UV_PYTHON_INSTALL_DIR=/opt/uv-python

# git 은 CosyVoice repo clone 에 필요. python:3.12-slim 에 없을 수 있어 보강.
if ! command -v git >/dev/null 2>&1; then
  apt-get update && apt-get install -y --no-install-recommends git ca-certificates
  rm -rf /var/lib/apt/lists/*
fi

# ════════════════════════════════════════════════════════════════════════════
# 1) Chatterbox — 컨테이너 system python(3.12)
# ════════════════════════════════════════════════════════════════════════════
echo "→ [heaxhub-build] (1/3) Chatterbox: torch/torchaudio ($TORCH_INDEX)"
# torch 를 먼저, 지정 인덱스로. chatterbox-tts 가 torch 를 핀버전으로 되돌리지 못하게 순서 고정.
pip install --no-cache-dir --index-url "$TORCH_INDEX" torch torchaudio

echo "→ [heaxhub-build] chatterbox-tts (--no-deps)"
pip install --no-cache-dir --no-deps "chatterbox-tts==0.1.7"

echo "→ [heaxhub-build] chatterbox 런타임 의존성(gradio 데모 UI 제외)"
pip install --no-cache-dir \
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

# uv — 사이드카 venv 용 python 3.10 을 받아온다(MeloTTS/CosyVoice 는 3.10 핀).
echo "→ [heaxhub-build] uv + python 3.10 (사이드카 venv 용)"
pip install --no-cache-dir uv
uv python install 3.10

# ════════════════════════════════════════════════════════════════════════════
# 2) MeloTTS — /app/backend/.venv-melo (python 3.10, CPU)
#    torch<2.0 / transformers 4.27 / librosa 0.9.1 을 핀 → 반드시 3.10.
#    가중치(한국어 BERT)는 런타임 /data/models 에서 온다(여기선 코드·사전만).
# ════════════════════════════════════════════════════════════════════════════
echo "→ [heaxhub-build] (2/3) MeloTTS 사이드카 venv"
cd /app/backend
uv venv --python 3.10 .venv-melo
.venv-melo/bin/python -m pip install --no-cache-dir --upgrade pip
.venv-melo/bin/pip install --no-cache-dir git+https://github.com/myshell-ai/MeloTTS.git
# unidic 사전(형태소 분석) — 런타임 다운로드가 없도록 빌드 때 내장(수백 MB, 코드/데이터라 SIF).
.venv-melo/bin/python -m unidic download
# librosa 0.9.1 이 pkg_resources 를 쓰는데 setuptools 81+ 가 제거 → 핀 없으면 런타임 ModuleNotFoundError.
.venv-melo/bin/pip install --no-cache-dir "setuptools<81"
# 한국어 g2p 가 런타임에 설치를 시도 → 폐쇄망 대비 미리 넣는다.
.venv-melo/bin/pip install --no-cache-dir python-mecab-ko || echo "  ⚠ python-mecab-ko 설치 실패(런타임 자동설치에 의존)"

# ════════════════════════════════════════════════════════════════════════════
# 3) CosyVoice3 — /app/vendor/CosyVoice(repo) + /app/backend/.venv-cosy (python 3.10, CPU)
#    torch 2.3.1(cpu). 코드는 공식 GitHub(Apache-2.0)를 clone 해 PYTHONPATH 로 쓴다
#    (PyPI cosyvoice 는 GPL-3.0 이라 안 씀). 가중치(~2GB)는 런타임 /data/models.
# ════════════════════════════════════════════════════════════════════════════
echo "→ [heaxhub-build] (3/3) CosyVoice repo clone (/app/vendor/CosyVoice)"
mkdir -p /app/vendor
if [ ! -d /app/vendor/CosyVoice/cosyvoice ]; then
  git clone --depth 1 --recursive https://github.com/FunAudioLLM/CosyVoice.git /app/vendor/CosyVoice
fi

echo "→ [heaxhub-build] CosyVoice 사이드카 venv + torch 2.3.1(cpu)"
cd /app/backend
uv venv --python 3.10 .venv-cosy
COSY_PIP=(env "VIRTUAL_ENV=/app/backend/.venv-cosy" uv pip install)
"${COSY_PIP[@]}" torch==2.3.1 torchaudio==2.3.1 --index-url https://download.pytorch.org/whl/cpu
# 추론에 필요한 것만(학습·GPU가속·서빙용 deepspeed/tensorrt/gradio/grpc/fastapi 제외 — optional import).
"${COSY_PIP[@]}" \
  conformer==0.3.2 diffusers==0.29.0 hydra-core==1.3.2 HyperPyYAML==1.2.3 \
  "librosa==0.10.2" lightning==2.2.4 omegaconf==2.3.0 onnx==1.16.0 onnxruntime==1.18.0 \
  transformers==4.51.3 wetext==0.0.4 soundfile "numpy==1.26.4" inflect==7.3.1 \
  x-transformers==2.11.24 pyworld==0.3.4 networkx==3.1 gdown rich \
  "matplotlib==3.7.5" wget==3.2 "pyarrow==18.1.0" "protobuf==4.25" "tensorboard==2.14.0"
# openai-whisper(speech tokenizer)는 pkg_resources 를 빌드에 요구 → setuptools 핀 + no-build-isolation.
"${COSY_PIP[@]}" "setuptools<81"
"${COSY_PIP[@]}" --no-build-isolation openai-whisper==20231117

# ════════════════════════════════════════════════════════════════════════════
# 검증 — 세 엔진의 import 경로가 SIF 안에서 살아있는지 조기 확인(하나라도 깨지면 빌드 실패).
# 가중치는 런타임 /data 에서 오므로 import 만 본다(모델 로드는 안 함).
# ════════════════════════════════════════════════════════════════════════════
echo "→ [heaxhub-build] 검증"
python - <<'PY'
import importlib.util as u
for m in ("torch", "chatterbox"):
    assert u.find_spec(m), f"system python: {m} MISSING"
print("  ✓ system python: torch + chatterbox")
PY
.venv-melo/bin/python -c "import melo; print('  ✓ .venv-melo: melo')"
.venv-cosy/bin/python -c "import torch; assert torch.__version__.startswith('2.3.1'); print('  ✓ .venv-cosy: torch', torch.__version__)"
test -f /app/vendor/CosyVoice/cosyvoice/cli/cosyvoice.py && echo "  ✓ CosyVoice repo"

echo "✓ [heaxhub-build] TTS 3엔진 스택 설치 완료 (가중치는 런타임 /data/models)"
