#!/usr/bin/env bash
# (온라인 호스트) 세 엔진의 가중치 + wetext FST 를 전부 var/models 로 받아 원스톱 조달한다.
# 폐쇄망 서버는 직접 못 받으므로 models-to-drive.sh → models-from-drive.sh 로 옮긴다.
#   - Chatterbox (MIT)        : 메인 venv 엔진
#   - CosyVoice3 (Apache-2.0) : 사이드카 엔진 (setup-cosy.sh 도 받지만 여기서 원스톱 커버)
#   - MeloTTS-Korean (MIT)    : 사이드카 엔진 + 부속 BERT
#   - wetext FST              : CosyVoice 텍스트 정규화 (modelscope, MODELSCOPE_CACHE 로 var/models 안에)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="${VOICEREC_MODELS_DIR:-$ROOT_DIR/var/models}"
PY="${VOICEREC_PYTHON_BIN:-$ROOT_DIR/backend/.venv/bin/python}"

[ -x "$PY" ] || { echo "✗ 백엔드 venv 없음 — scripts/setup-backend.sh 를 먼저 실행하세요"; exit 1; }
mkdir -p "$MODELS_DIR"

echo "→ HuggingFace 가중치 → $MODELS_DIR"
HF_HOME="$MODELS_DIR" "$PY" - <<'PY'
from pathlib import Path
from huggingface_hub import snapshot_download

# allow_patterns 없이 리포 통째 — 다국어 토크나이저·부속 파일까지 있어야 HF_HUB_OFFLINE 에서 무경고.
repos = [
    "ResembleAI/chatterbox",
    "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
    "myshell-ai/MeloTTS-Korean",
]
for repo in repos:
    p = snapshot_download(repo)
    size = sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file())
    print(f"  ✓ {repo}  ({size / 2**30:.2f} GB)")

# MeloTTS 부속 BERT — melo 는 import 할 때 모든 언어 모듈이 자기 토크나이저를 불러온다(한국어만 써도).
# 하나라도 캐시에 없으면 HF_HUB_OFFLINE 에서 합성 전에 OSError 로 죽는다(2026-10-24 포털 실측:
# tohoku-nlp/bert-base-japanese-v3 를 못 찾음). 한국어 BERT 만 가중치가 필요하고 나머지는 토크나이저 파일뿐이다.
melo_aux = {
    "kykim/bert-kor-base": ["config.json", "pytorch_model.bin", "tokenizer_config.json", "vocab.txt"],
    "tohoku-nlp/bert-base-japanese-v3": ["tokenizer_config.json", "vocab.txt"],
    "bert-base-uncased": ["config.json", "tokenizer_config.json", "tokenizer.json", "vocab.txt"],
    "bert-base-multilingual-uncased": ["config.json", "tokenizer_config.json", "tokenizer.json", "vocab.txt"],
    "dbmdz/bert-base-french-europeana-cased": ["config.json", "tokenizer_config.json", "vocab.txt"],
    "dccuchile/bert-base-spanish-wwm-uncased": [
        "config.json", "special_tokens_map.json", "tokenizer_config.json", "tokenizer.json", "vocab.txt",
    ],
}
for repo, files in melo_aux.items():
    p = snapshot_download(repo, allow_patterns=files)
    size = sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file())
    print(f"  ✓ {repo}  ({size / 2**20:.1f} MB, MeloTTS 부속)")
PY

# ── wetext FST (CosyVoice 정규화) — modelscope 캐시를 var/models 안에 받는다 ──
# CosyVoice 사이드카 venv 에서만 import 되므로 그 venv 로 트리거한다. 없으면 건너뛴다
# (setup-cosy.sh 실행 시 자동으로 받히고, 어차피 var/models 통째로 Drive 에 실린다).
COSY_PY="$ROOT_DIR/backend/.venv-cosy/bin/python"
if [ -x "$COSY_PY" ]; then
  echo "→ wetext FST → $MODELS_DIR/modelscope"
  MODELSCOPE_CACHE="$MODELS_DIR/modelscope" "$COSY_PY" - <<'PY'
try:
    from wetext import Normalizer
    Normalizer(lang="auto", operator="tn")  # 첫 로드가 FST 를 캐시에 받는다
    print("  ✓ wetext FST")
except Exception as e:  # noqa
    print(f"  ⚠ wetext 스킵({e}) — setup-cosy.sh 실행 시 받힘")
PY
else
  echo "· CosyVoice 사이드카 venv 없음 — wetext 는 setup-cosy.sh 에서 받힘"
fi

echo
echo "✓ 완료 ($(du -sh "$MODELS_DIR" | cut -f1)). 폐쇄망으로: scripts/models-to-drive.sh"
