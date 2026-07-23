#!/usr/bin/env bash
# (폐쇄망 서버) Drive 에서 모델 가중치를 받아 앱이 보는 경로에 놓는다.
# 받은 뒤에는 HF_HUB_OFFLINE=1 로 런타임이 네트워크를 아예 안 타게 한다(매니페스트에 설정됨).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="${VOICEREC_MODELS_DIR:-$ROOT_DIR/var/models}"

env_get() {
  local file="$1" key="$2"
  [ -f "$file" ] && sed -n "s/^$key=//p" "$file" | tail -1 | sed 's/^["'"'"']//; s/["'"'"']$//'
}

REMOTE="${HEAX_DRIVE_REMOTE:-}"
[ -n "$REMOTE" ] || REMOTE="$(env_get "$ROOT_DIR/.env" HEAX_DRIVE_REMOTE)"
[ -n "$REMOTE" ] || REMOTE="$(env_get "${HEAXHUB_DIR:-$ROOT_DIR/../HEAXHub}/.env" HEAX_DRIVE_REMOTE)"
[ -n "$REMOTE" ] || { echo "✗ HEAX_DRIVE_REMOTE 미설정"; exit 1; }

command -v rclone >/dev/null 2>&1 || { echo "✗ rclone 미설치"; exit 1; }

REMOTE="${REMOTE%/}"; REMOTE="${REMOTE%/dist}"
SRC="$REMOTE/models/voice_recorder"

mkdir -p "$MODELS_DIR"
echo "→ $SRC → $MODELS_DIR"
rclone copy "$SRC" "$MODELS_DIR" --transfers 4 --checkers 8 --progress --stats-one-line

echo
if [ -d "$MODELS_DIR/hub" ]; then
  echo "✓ 완료 ($(du -sh "$MODELS_DIR" | cut -f1))"
  echo "  앱 환경변수: HF_HOME=$MODELS_DIR  HF_HUB_OFFLINE=1"
else
  echo "⚠ hub/ 디렉터리가 없습니다 — 업로드가 비어 있거나 경로가 다를 수 있습니다."
  exit 1
fi
