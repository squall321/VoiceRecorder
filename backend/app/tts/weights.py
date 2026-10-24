# 오프라인(HF_HUB_OFFLINE=1)에서 엔진 가중치가 캐시에 실제로 있는지 본다 — 없으면 합성 때에야 OSError 로 죽는다

"""엔진 status() 가 '설치됨'만 보고 '준비됨'이라 하면, 가중치가 비어 있는 폐쇄망·포털에서는 합성을
눌러야 비로소 "couldn't connect to huggingface.co" 로 실패한다(2026-10-24 포털 실측: 모델 폴더가 비어
세 엔진 모두 합성 불가였는데 화면은 전부 '준비됨'). 오프라인일 때만 캐시를 확인한다 — 온라인이면
첫 합성 때 받아 오므로 막을 이유가 없다.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from .. import config


def offline() -> bool:
    return os.environ.get("HF_HUB_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


def _hf_hub() -> Path:
    # 엔진들이 HF_HOME 을 정하는 규칙과 같다(chatterbox_engine·cosy_engine 의 setdefault).
    return Path(os.environ.get("HF_HOME") or config.MODELS_DIR) / "hub"


def _modelscope_models() -> Path:
    return Path(os.environ.get("MODELSCOPE_CACHE") or (config.MODELS_DIR / "modelscope")) / "models"


def _has_files(folder: Path) -> bool:
    # 스냅샷 파일은 blobs 로 가는 심볼릭 링크다 — is_file() 이 링크를 따라가 실제 내용이 있는지 본다
    return folder.is_dir() and any(p.is_file() for p in folder.rglob("*"))


def missing(repos: Iterable[str], modelscope: Iterable[str] = ()) -> list[str]:
    """오프라인일 때 캐시에 없는 저장소 이름들. 온라인이면 빈 목록."""
    if not offline():
        return []
    hub = _hf_hub()
    lacking = [r for r in repos if not _has_files(hub / f"models--{r.replace('/', '--')}" / "snapshots")]
    ms = _modelscope_models()
    lacking += [r for r in modelscope if not _has_files(ms / r.replace("/", "--") / "snapshots")]
    return lacking


def missing_detail(lacking: list[str]) -> str:
    head = ", ".join(lacking[:2]) + (f" 외 {len(lacking) - 2}개" if len(lacking) > 2 else "")
    return f"모델 가중치 없음(오프라인) — {head}. scripts/models-from-drive.sh 로 받으세요"
