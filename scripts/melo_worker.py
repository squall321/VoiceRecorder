# MeloTTS 사이드카 venv(.venv-melo) 안에서 도는 상주 합성 워커
#
# 요청 하나당 프로세스를 새로 띄우면 매번 모델을 다시 올려 씬당 2분이 넘는다.
# 그래서 stdin 에서 JSON 을 한 줄씩 계속 읽고 stdout 으로 한 줄씩 답하는 상주 방식으로 둔다.
# 프로토콜:  {"text":..,"language":"KR","out":"/path.wav"}\n  →  {"ok":true,"out":..}\n
#            잘못된 요청/실패는 {"ok":false,"error":".."} 로 답하고 프로세스는 살아 있는다.

from __future__ import annotations

import json
import sys

_MODELS: dict[str, object] = {}


def _model(language: str):
    model = _MODELS.get(language)
    if model is None:
        from melo.api import TTS

        model = TTS(language=language, device="cpu")
        _MODELS[language] = model
    return model


def _synthesize(request: dict) -> dict:
    language = request.get("language", "KR")
    out_path = request["out"]
    model = _model(language)

    # spk2id 는 dict 가 아니라 MeloTTS 의 HParams 객체다 (.get() 없음).
    speaker_ids = model.hps.data.spk2id
    keys = list(speaker_ids.keys())
    speaker_id = speaker_ids[language if language in keys else keys[0]]

    # 속도는 여기서 건드리지 않는다 — 엔진 밖 ffmpeg atempo 가 일괄 처리한다.
    model.tts_to_file(request["text"], speaker_id, out_path, speed=1.0)
    return {"ok": True, "out": out_path}


def main() -> int:
    # 모델 로딩 로그가 stdout 을 오염시키면 프로토콜이 깨진다. 전부 stderr 로 보낸다.
    real_stdout = sys.stdout
    sys.stdout = sys.stderr

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            response = _synthesize(json.loads(line))
        except Exception as exc:  # noqa: BLE001 - 실패해도 워커는 살아 있어야 한다
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(response, ensure_ascii=False), file=real_stdout, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
