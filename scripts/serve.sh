#!/usr/bin/env bash
# HEAX 연합 오케스트레이터(HWAXPortal services.yaml)가 부르는 시작 스크립트 — 백엔드를 :8177 로 띄운다.
# MXWhitePaper·MaterialTwinWeb 처럼 재부팅 시 hwax-stack.service(linger)가 자동 기동한다.
#
# VoiceRecorder 는 torch(cu130)+Chatterbox 메인 venv 와 CosyVoice 사이드카(.venv-cosy)를 쓰는
# 무거운 앱이라 HEAXHub SIF 표준 빌드에 안 담긴다. 그래서 heax-hub 안의 앱이 아니라
# 자체 venv 로 도는 독립 서비스로 등록한다 (mx-white-paper 방식).
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

PORT="${VOICEREC_PORT:-8177}"
# 오케스트레이터가 detach 하므로 foreground 로 exec (Chatterbox 는 GPU 여유 없으면 CPU 폴백).
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
