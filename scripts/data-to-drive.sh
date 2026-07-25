#!/usr/bin/env bash
# (호스트) VoiceRecorder 운영 데이터(var/data: 프로젝트 DB + 생성 오디오)를 rclone Drive 로 백업한다.
#
# 모델(models-to-drive.sh)과 달리 이건 "사용자가 만든 것" — 프로젝트·씬·보이스·발음사전(DB)과
# 합성된 wav/mp3. HEAXHub appdata-to-drive.sh 와 같은 방식: SQLite 는 .backup 으로 원자적
# 스냅샷 후 tar (쓰기 중에도 일관). 같은 Drive remote(HEAX_DRIVE_REMOTE)의 app-data/ 하위.
#   → 업로드 위치  <remote>:HEAXHub/app-data/voice_recorder/{data-<TS>, latest}/
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${VOICEREC_DATA_DIR:-$ROOT_DIR/var/data}"
PY="${VOICEREC_PYTHON_BIN:-$ROOT_DIR/backend/.venv/bin/python}"

env_get() { local f="$1" k="$2"; [ -f "$f" ] || return 0; sed -n "s/^$k=//p" "$f" | tail -1 | sed 's/^["'"'"']//; s/["'"'"']$//'; }
REMOTE="${HEAX_DRIVE_REMOTE:-}"
[ -n "$REMOTE" ] || REMOTE="$(env_get "$ROOT_DIR/.env" HEAX_DRIVE_REMOTE)"
[ -n "$REMOTE" ] || REMOTE="$(env_get "${HEAXHUB_DIR:-$ROOT_DIR/../HEAXHub}/.env" HEAX_DRIVE_REMOTE)"
[ -n "$REMOTE" ] || { echo "✗ HEAX_DRIVE_REMOTE 미설정 (예: ApptainerImages:HEAXHub/dist)"; exit 1; }
command -v rclone >/dev/null 2>&1 || { echo "✗ rclone 미설치"; exit 1; }
[ -d "$DATA_DIR" ] && [ -n "$(ls -A "$DATA_DIR" 2>/dev/null)" ] || { echo "· var/data 비어있음 — 백업 대상 없음"; exit 0; }

REMOTE="${REMOTE%/}"; REMOTE="${REMOTE%/dist}"
DEST="$REMOTE/app-data/voice_recorder"
RETAIN="${HEAX_DRIVE_RETAIN:-$(env_get "$ROOT_DIR/.env" HEAX_DRIVE_RETAIN)}"; RETAIN="${RETAIN:-5}"
TS="$(date -u +%Y%m%d-%H%M%SZ)"

STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
SNAP="$STAGE/data"; mkdir -p "$SNAP"
cp -a "$DATA_DIR/." "$SNAP/"

# SQLite 는 WAL 사본 대신 .backup 원자적 스냅샷으로 교체 (쓰기 중에도 일관).
[ -x "$PY" ] && "$PY" - "$DATA_DIR" "$SNAP" <<'PY' || echo "  ⚠ python 없음 — DB 는 파일 사본 그대로"
import sys, glob, os, sqlite3
src, snap = sys.argv[1], sys.argv[2]
for db in glob.glob(os.path.join(src, "**", "*.db"), recursive=True):
    rel = os.path.relpath(db, src); dst = os.path.join(snap, rel)
    for ext in ("-wal", "-shm"):
        if os.path.exists(dst + ext): os.remove(dst + ext)
    try:
        s = sqlite3.connect(f"file:{db}?mode=ro", uri=True); d = sqlite3.connect(dst)
        s.backup(d); d.close(); s.close(); print(f"  · 스냅샷 {rel}")
    except Exception as e:
        print(f"  ⚠ {rel} 스냅샷 실패({e}) — 원본 사본 유지")
PY

tar -czf "$STAGE/data.tar.gz" -C "$SNAP" .
SZ="$(du -h "$STAGE/data.tar.gz" | cut -f1)"
echo "→ 업로드 $DEST/data-$TS/  (+ latest/)  [$SZ]"
rclone copyto "$STAGE/data.tar.gz" "$DEST/data-$TS/data.tar.gz" --stats-one-line
rclone copyto "$STAGE/data.tar.gz" "$DEST/latest/data.tar.gz" --stats-one-line

# 오래된 스냅샷 정리 (latest 제외, 최근 RETAIN 개만 유지)
mapfile -t OLD < <(rclone lsf "$DEST" --dirs-only 2>/dev/null | grep '^data-' | sort | head -n -"$RETAIN")
for d in "${OLD[@]:-}"; do [ -n "$d" ] && rclone purge "$DEST/$d" 2>/dev/null && echo "  · 정리 $d"; done

echo "✓ 완료. 폐쇄망 서버에서: scripts/data-from-drive.sh"
