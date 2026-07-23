# MeloTTS 사이드카 venv(.venv-melo) 안에서 실행되는 합성 워커 — stdin 으로 JSON 을 받는다

from __future__ import annotations

import json
import sys


def main() -> int:
    request = json.load(sys.stdin)
    language = request.get("language", "KR")
    out_path = request["out"]

    from melo.api import TTS

    model = TTS(language=language, device="cpu")
    speaker_ids = model.hps.data.spk2id
    speaker_id = speaker_ids.get(language, next(iter(speaker_ids.values())))
    # 속도는 여기서 건드리지 않는다 — 엔진 밖 ffmpeg atempo 가 일괄 처리한다.
    model.tts_to_file(request["text"], speaker_id, out_path, speed=1.0)
    print(json.dumps({"ok": True, "out": out_path}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
