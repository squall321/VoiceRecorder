#!/usr/bin/env bash
# (온라인 호스트) Chatterbox 가중치를 HuggingFace 에서 var/models 로 받아둔다.
# 폐쇄망 서버는 이걸 직접 못 하므로 models-to-drive.sh → models-from-drive.sh 로 옮긴다.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="${VOICEREC_MODELS_DIR:-$ROOT_DIR/var/models}"
PY="${VOICEREC_PYTHON_BIN:-$ROOT_DIR/backend/.venv/bin/python}"

[ -x "$PY" ] || { echo "✗ 백엔드 venv 가 없습니다 — scripts/setup-backend.sh 를 먼저 실행하세요"; exit 1; }

mkdir -p "$MODELS_DIR"
echo "→ ResembleAI/chatterbox → $MODELS_DIR"

HF_HOME="$MODELS_DIR" "$PY" - <<'PY'
import os
from huggingface_hub import snapshot_download

# allow_patterns 를 쓰지 않는다 — 다국어 토크나이저가 Cangjie 매핑 등 부속 파일을
# 런타임에 찾으므로 리포를 통째로 받아야 HF_HUB_OFFLINE=1 에서 경고가 안 뜬다.
path = snapshot_download("ResembleAI/chatterbox")
size = sum(f.stat().st_size for f in __import__("pathlib").Path(path).rglob("*") if f.is_file())
print(f"  ✓ {path}")
print(f"  ✓ {size / 2**30:.2f} GB")
PY

echo
echo "✓ 완료. 폐쇄망으로 보내려면: scripts/models-to-drive.sh"
