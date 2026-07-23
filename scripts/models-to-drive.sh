#!/usr/bin/env bash
# (온라인 호스트) 모델 가중치를 rclone Google Drive 로 올린다.
#
# 운영 서버(cae00)는 사내 TLS 인터셉트 망이라 HuggingFace/PyPI/DockerHub 에 못 닿는다.
# Chatterbox 가중치가 ~3GB 라 git 에도 넣을 수 없어서, HEAXHub 가 이미 쓰는 Drive remote 를
# 그대로 재사용한다 (dist-to-drive.sh / appdata-to-drive.sh 와 같은 remote, models/ 형제 폴더).
#
#   .env 또는 HEAXHub/.env 의  HEAX_DRIVE_REMOTE=<remote>:HEAXHub/dist
#   → 업로드 위치            <remote>:HEAXHub/models/voice_recorder/
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
[ -n "$REMOTE" ] || { echo "✗ HEAX_DRIVE_REMOTE 미설정 (예: ApptainerImages:HEAXHub/dist)"; exit 1; }

command -v rclone >/dev/null 2>&1 || { echo "✗ rclone 미설치 (https://rclone.org/install/)"; exit 1; }
[ -d "$MODELS_DIR" ] || { echo "✗ $MODELS_DIR 없음 — scripts/fetch-models.sh 를 먼저 실행하세요"; exit 1; }

REMOTE="${REMOTE%/}"; REMOTE="${REMOTE%/dist}"      # dist 형제로 models/ 사용
DEST="$REMOTE/models/voice_recorder"

SIZE="$(du -sh "$MODELS_DIR" | cut -f1)"
echo "→ $MODELS_DIR ($SIZE) → $DEST"

# sync 가 아니라 copy 다 — 원격에만 있는 다른 모델을 지우지 않는다.
rclone copy "$MODELS_DIR" "$DEST" \
  --transfers 4 --checkers 8 --progress --stats-one-line

echo
echo "✓ 업로드 완료. 폐쇄망 서버에서: scripts/models-from-drive.sh"
