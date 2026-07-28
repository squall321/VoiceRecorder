#!/usr/bin/env bash
# HEAXHub SIF 빌드 훅 — fastapi_react.def Stage3 가 `pip install -e .` 뒤에 호출한다.
# pyproject 밖으로 뺀 TTS 스택(torch + chatterbox-tts)을 컨테이너 **시스템 python** 에
# 설치한다(개발용 scripts/setup-backend.sh 는 venv + cu130(RTX50) 이라 컨테이너/서버엔
# 부적합 — 여기서 순서만 그대로 재현하되 venv 를 안 쓴다).
#
# torch 기본은 CPU 휠 — 서버 하드웨어와 무관하게 동작한다(TTS 는 느려도 됨). GPU 서버면
# 빌드 시 VOICEREC_TORCH_INDEX 로 CUDA 휠을 지정한다(예: .../whl/cu121).
#
# 주의: 이 훅은 빌드 시점에 pytorch.org/PyPI 에 닿아야 한다 → **온라인 박스에서 fat SIF
# 를 빌드**하고 dist-to-drive(per-app SIF)로 폐쇄망 서버에 나른다. 폐쇄망에서 직접 빌드
# 하려면 torch/chatterbox 휠을 사내 미러(BUILD_PIP_*)에 넣어야 한다(torch 는 수 GB).
set -euo pipefail

TORCH_INDEX="${VOICEREC_TORCH_INDEX:-https://download.pytorch.org/whl/cpu}"

# 1) torch 를 먼저, 지정 인덱스로. chatterbox-tts 가 torch 를 되돌리지 못하게 순서 고정.
echo "→ [heaxhub-build] torch/torchaudio ($TORCH_INDEX)"
pip install --no-cache-dir --index-url "$TORCH_INDEX" torch torchaudio

# 2) chatterbox 는 의존성 없이(안 그러면 pip 가 torch 를 핀버전으로 되돌린다).
echo "→ [heaxhub-build] chatterbox-tts (--no-deps)"
pip install --no-cache-dir --no-deps "chatterbox-tts==0.1.7"

# 3) chatterbox 가 실제로 쓰는 런타임 의존성만(gradio 데모 UI 제외).
echo "→ [heaxhub-build] chatterbox 런타임 의존성"
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

# 검증 — SIF 안에서 chatterbox/torch 가 import 되면 TTS status().available 이 켜진다.
python - <<'PY'
import importlib.util as u
for m in ("torch", "chatterbox"):
    print(f"  [heaxhub-build] find_spec({m}) = {'OK' if u.find_spec(m) else 'MISSING'}")
PY
echo "✓ [heaxhub-build] TTS 스택 설치 완료(컨테이너 시스템 python)"
