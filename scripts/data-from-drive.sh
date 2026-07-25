#!/usr/bin/env bash
# (폐쇄망 서버) Drive 에서 운영 데이터(var/data)를 받아 복원한다. 기본은 latest 스냅샷.
# 기존 var/data 가 있으면 덮어쓰기 전에 .bak 으로 물러둔다 (실수 복구용).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${VOICEREC_DATA_DIR:-$ROOT_DIR/var/data}"
SNAPSHOT="${1:-latest}"   # latest | data-<TS>

env_get() { local f="$1" k="$2"; [ -f "$f" ] || return 0; sed -n "s/^$k=//p" "$f" | tail -1 | sed 's/^["'"'"']//; s/["'"'"']$//'; }
REMOTE="${HEAX_DRIVE_REMOTE:-}"
[ -n "$REMOTE" ] || REMOTE="$(env_get "$ROOT_DIR/.env" HEAX_DRIVE_REMOTE)"
[ -n "$REMOTE" ] || REMOTE="$(env_get "${HEAXHUB_DIR:-$ROOT_DIR/../HEAXHub}/.env" HEAX_DRIVE_REMOTE)"
[ -n "$REMOTE" ] || { echo "✗ HEAX_DRIVE_REMOTE 미설정"; exit 1; }
command -v rclone >/dev/null 2>&1 || { echo "✗ rclone 미설치"; exit 1; }

REMOTE="${REMOTE%/}"; REMOTE="${REMOTE%/dist}"
SRC="$REMOTE/app-data/voice_recorder/$SNAPSHOT/data.tar.gz"

STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
echo "→ $SRC 받는 중"
rclone copyto "$SRC" "$STAGE/data.tar.gz" --stats-one-line || { echo "✗ 스냅샷 없음: $SRC"; exit 1; }

if [ -d "$DATA_DIR" ] && [ -n "$(ls -A "$DATA_DIR" 2>/dev/null)" ]; then
  BAK="$DATA_DIR.bak-$(date -u +%Y%m%d-%H%M%SZ)"
  echo "· 기존 var/data → $BAK 로 물러둠"
  mv "$DATA_DIR" "$BAK"
fi
mkdir -p "$DATA_DIR"
tar -xzf "$STAGE/data.tar.gz" -C "$DATA_DIR"

echo "✓ 복원 완료 ($(du -sh "$DATA_DIR" | cut -f1))"
echo "  DB: $(ls "$DATA_DIR"/*.db 2>/dev/null || echo '없음') · 프로젝트 $(ls "$DATA_DIR/projects" 2>/dev/null | wc -l)개"
