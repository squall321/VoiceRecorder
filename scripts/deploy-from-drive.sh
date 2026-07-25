#!/usr/bin/env bash
# (폐쇄망 서버) Drive 에서 데이터 일체를 원스톱 복원한다 — 모델 가중치 + wetext FST + 운영 데이터.
# 코드는 git clone, venv 는 setup-backend.sh/setup-cosy.sh(온라인 또는 사내 pip 미러)로 별도 준비한다
# (venv 는 플랫폼 종속이라 Drive 로 옮기지 않는다).
#
# 온라인 스테이징에서 미리:  scripts/fetch-models.sh → models-to-drive.sh → data-to-drive.sh
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "══ VoiceRecorder 폐쇄망 데이터 복원 ══"
echo "[1/2] 모델 가중치 + wetext FST (var/models)"
scripts/models-from-drive.sh

echo
echo "[2/2] 운영 데이터 (var/data: 프로젝트 DB + 생성 오디오)"
scripts/data-from-drive.sh || echo "  · 데이터 스냅샷 없음 — 신규 배포면 정상 (빈 상태로 시작)"

echo
echo "✓ 데이터 복원 완료. 남은 것:"
echo "  · venv 없으면:  scripts/setup-backend.sh  +  scripts/setup-cosy.sh  (온라인/사내 미러)"
echo "  · 기동:         HEAX 연합에 등록돼 있으면 재부팅 자동, 수동은 scripts/serve.sh"
