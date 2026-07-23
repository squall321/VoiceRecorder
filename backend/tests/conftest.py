# 테스트용 데이터 디렉터리를 app 임포트 전에 잡아준다 (config 가 임포트 시점에 경로를 확정한다)

from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="voicerec-test-")
os.environ["VOICEREC_DATA_DIR"] = _TMP
os.environ.setdefault("VOICEREC_MODELS_DIR", os.path.join(_TMP, "models"))
