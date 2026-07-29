#!/usr/bin/env bash
# 로컬 개발용 편의 실행 스크립트 — 호스트 venv 로 백엔드를 :8177 에 띄운다.
#
# ⚠ HEAX 연동/배포는 이 스크립트가 아니다. 다른 HEAX 앱과 똑같이 HEAXHub 가 SIF 로 빌드·서빙한다
# (integrations/voice-recorder/, /apps/voice_recorder/). torch+Chatterbox 와 MeloTTS/CosyVoice
# 사이드카는 fastapi_react.def Stage3 훅(scripts/heaxhub-build.sh)이 컨테이너에 심고, 가중치는
# /data 볼륨으로 나른다. 이 파일은 SIF 없이 로컬에서 빠르게 돌려볼 때만 쓴다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

# 폐쇄망/오프라인: 가중치는 var/models, 런타임은 네트워크를 타지 않는다.
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export HF_HOME="${HF_HOME:-$ROOT/var/models}"
export VOICEREC_MODELS_DIR="${VOICEREC_MODELS_DIR:-$ROOT/var/models}"
export VOICEREC_DATA_DIR="${VOICEREC_DATA_DIR:-$ROOT/var/data}"
# CosyVoice 사이드카 워커가 참조하는 repo 경로.
export COSYVOICE_REPO="${COSYVOICE_REPO:-$ROOT/vendor/CosyVoice}"
# wetext(텍스트 정규화)의 modelscope FST 캐시도 var/models 안에 둔다 → Drive 전송에 함께 포함되고
# 폐쇄망에서 modelscope.cn 재접속이 필요 없다.
export MODELSCOPE_CACHE="${MODELSCOPE_CACHE:-$ROOT/var/models/modelscope}"

PORT="${VOICEREC_PORT:-8177}"
# 오케스트레이터가 detach 하므로 foreground 로 exec (Chatterbox 는 GPU 여유 없으면 CPU 폴백).
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
