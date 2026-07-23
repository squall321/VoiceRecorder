# 런타임 경로·기본값 설정. SIF rootfs 는 read-only 라 쓰기는 전부 DATA_DIR 아래에서만 한다

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_data_dir() -> Path:
    """쓰기 가능한 데이터 루트를 고른다.

    운영(HEAXHub SIF): 매니페스트가 VOICEREC_DATA_DIR=/data 를 주입하고 포탈이
    var/app_data/voice_recorder/ 를 거기에 바인드한다.
    로컬 개발: 리포 안의 var/data 를 쓴다.
    """
    env = os.environ.get("VOICEREC_DATA_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "var" / "data"


DATA_DIR = _resolve_data_dir()
DB_PATH = DATA_DIR / "voicerecorder.db"
PROJECTS_DIR = DATA_DIR / "projects"
VOICES_DIR = DATA_DIR / "voices"
UPLOADS_DIR = DATA_DIR / "uploads"

# 모델 가중치는 리포에 넣지 않는다 (Drive 경유, scripts/models-*-drive.sh).
# 폐쇄망에서는 HF_HUB_OFFLINE=1 로 네트워크를 아예 안 타게 막는다.
MODELS_DIR = Path(os.environ.get("VOICEREC_MODELS_DIR") or (_REPO_ROOT / "var" / "models"))

DEFAULT_ENGINE = os.environ.get("VOICEREC_DEFAULT_ENGINE", "chatterbox")
DEFAULT_LANGUAGE = os.environ.get("VOICEREC_DEFAULT_LANGUAGE", "ko")
DEFAULT_GAP_MS = int(os.environ.get("VOICEREC_DEFAULT_GAP_MS", "400"))
MP3_BITRATE = os.environ.get("VOICEREC_MP3_BITRATE", "192k")

# 한 번에 모델로 넘기는 최대 글자 수. 넘으면 문장 경계로 쪼개 합성 후 이어 붙인다.
MAX_CHARS_PER_CHUNK = int(os.environ.get("VOICEREC_MAX_CHARS", "300"))
# 쪼갠 조각 사이에 넣는 짧은 숨 (초)
CHUNK_GAP_SEC = float(os.environ.get("VOICEREC_CHUNK_GAP_SEC", "0.18"))

# 참조 음성 업로드 상한 (바이트)
MAX_VOICE_UPLOAD_BYTES = int(os.environ.get("VOICEREC_MAX_VOICE_BYTES", str(20 * 1024 * 1024)))


def ensure_dirs() -> None:
    for path in (DATA_DIR, PROJECTS_DIR, VOICES_DIR, UPLOADS_DIR, MODELS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def scene_raw_path(project_id: str, scene_id: str) -> Path:
    """엔진이 뱉은 원본 wav — 속도 조절 전. 텍스트/화자가 안 바뀌면 재사용한다."""
    return project_dir(project_id) / "raw" / f"{scene_id}.wav"


def scene_audio_path(project_id: str, scene_id: str) -> Path:
    """속도까지 반영된 최종 wav. 미리듣기·병합이 쓰는 파일."""
    return project_dir(project_id) / "scenes" / f"{scene_id}.wav"


def export_mp3_path(project_id: str) -> Path:
    return project_dir(project_id) / "export" / "narration.mp3"


def export_srt_path(project_id: str) -> Path:
    return project_dir(project_id) / "export" / "narration.srt"
