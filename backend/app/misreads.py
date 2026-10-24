# MeloTTS 한국어가 실제로 잘못 읽었던 말과 그때 쓴 우회 표기 — 씬에 나오면 화면이 알려 주고 한 번에 읽는 법에 넣게 한다

"""2026-07~10 내레이션 녹음에서 사용자가 귀로 확인한 MeloTTS(KR) 오독 목록이다.
뜻이 바뀌는 우회(상위 → 가장 많은)도 있어서 자동으로 바꾸지 않고, 씬 카드에 알려 사람이 고르게 한다.
정규화가 끝난 합성 텍스트에서 찾으므로 읽는 법·사전으로 이미 바꾼 말은 다시 알리지 않는다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Misread:
    word: str  # 합성 텍스트에 나오는 말
    heard: str  # 실제로 들린 소리
    suggest: str | None  # 읽는 법에 넣을 우회 표기 (없으면 바꿔 쓰라는 안내만)
    confirmed: bool = True  # 우회 표기를 귀로 확인했는지


MELO_MISREADS: tuple[Misread, ...] = (
    Misread("응력", "음력", "응녁"),
    Misread("기준도", "비준도", "체계도"),
    Misread("기준의", "비준의", None),
    Misread("상위", "삼위", "가장 많은"),
    Misread("대책", "대체", "대응책"),
    Misread("연계", "연기", "연결"),
    Misread("규명", "비명", None),
    Misread("변경점만으로", "변경 전만으로", "변경 내용만으로"),
    Misread("설명회 변경", "설명을 변경", "설명회의 변경"),
    Misread("정검출", "점검 줄", "정확히 검출한 것"),
    Misread("전위치", "저뉘치", "전 위치"),
    Misread("심의", "심해·침해", "시미", confirmed=False),
)


def misread_hints(spoken_text: str, engine: str) -> list[dict]:
    """합성 텍스트에 나오는 알려진 오독 — 지금은 MeloTTS 에서만 확인된 목록이다."""
    if engine != "melo" or not spoken_text:
        return []
    return [asdict(m) for m in MELO_MISREADS if m.word in spoken_text]
