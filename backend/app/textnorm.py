# 합성 직전 텍스트 정규화 — 숫자·기호를 한국어 읽는 소리로 바꾸고 사용자 치환 사전을 적용한다

from __future__ import annotations

import re

# ── 한자어 수사 (일이삼…) ────────────────────────────────────────────────────
_SINO_DIGITS = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
_SINO_SMALL = ["", "십", "백", "천"]
_SINO_BIG = ["", "만", "억", "조", "경"]

# ── 고유어 수사 (하나둘셋…) — 단위명사 앞에서는 관형형(한·두·세·네·스무)을 쓴다 ──
_NATIVE_ONES = ["", "하나", "둘", "셋", "넷", "다섯", "여섯", "일곱", "여덟", "아홉"]
_NATIVE_ONES_ATTR = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
_NATIVE_TENS = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]
_NATIVE_TENS_ATTR = ["", "열", "스무", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]

# 고유어로 세는 단위명사. 이 앞의 1~99 는 '세 개', '스무 명' 처럼 읽는다.
_NATIVE_COUNTERS = (
    "개",
    "명",
    "시",  # 시각은 고유어 — '세 시'. 반면 '분'은 한자어라 여기 없다 ('삼십 분')
    "살",
    "마리",
    "번",
    "대",
    "장",
    "권",
    "켤레",
    "그루",
    "송이",
    "가지",
    "군데",
    "차례",
    "달",
    "잔",
    "채",
    "벌",
    "쌍",
)

# 기호 → 읽는 소리
_SYMBOL_MAP = {
    "℃": "도",
    "°C": "도",
    "℉": "화씨",
    "%": "퍼센트",
    "㎜": "밀리미터",
    "㎝": "센티미터",
    "㎞": "킬로미터",
    "㎏": "킬로그램",
    "㎡": "제곱미터",
    "&": "앤드",
    "+": "플러스",
    "=": "는",
}

_NUMBER_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")
_RANGE_RE = re.compile(r"(?<=\d)\s*[~∼]\s*(?=\d)")
# 앞뒤가 공백인 대시만 삽입구로 본다 (A-1, 3-4 같은 건 제외)
_INLINE_DASH_RE = re.compile(r"\s+[—–]\s+|\s+-\s+")


def sino_korean(n: int) -> str:
    """정수를 한자어 수사로 읽는다. 0 → '영', 10 → '십', 21 → '이십일'."""
    if n == 0:
        return "영"
    if n < 0:
        return "마이너스 " + sino_korean(-n)

    groups: list[int] = []
    while n > 0:
        groups.append(n % 10000)
        n //= 10000

    parts: list[str] = []
    for pos in range(len(groups) - 1, -1, -1):
        group = groups[pos]
        if group == 0:
            continue
        chunk = ""
        for digit_pos in range(3, -1, -1):
            digit = (group // (10**digit_pos)) % 10
            if digit == 0:
                continue
            # 십·백·천 자리의 1 은 읽지 않는다 — '일십' 이 아니라 '십'
            chunk += ("" if digit == 1 and digit_pos > 0 else _SINO_DIGITS[digit]) + _SINO_SMALL[digit_pos]
        big = _SINO_BIG[pos] if pos < len(_SINO_BIG) else ""
        # '일만' 도 그냥 '만' 으로 읽는다
        if chunk == "일" and big:
            chunk = ""
        parts.append(chunk + big)
    return "".join(parts)


def native_korean(n: int, *, attributive: bool = False) -> str:
    """1~99 를 고유어 수사로 읽는다. attributive=True 면 단위명사 앞 관형형."""
    if not 1 <= n <= 99:
        return sino_korean(n)
    tens, ones = divmod(n, 10)
    tens_tbl = _NATIVE_TENS_ATTR if attributive else _NATIVE_TENS
    ones_tbl = _NATIVE_ONES_ATTR if attributive else _NATIVE_ONES
    # '스무' 는 뒤에 자릿수가 붙으면 다시 '스물' 이 된다 — 스무 개 / 스물한 개
    tens_word = _NATIVE_TENS[tens] if (attributive and ones) else tens_tbl[tens]
    return tens_word + ones_tbl[ones]


def _read_decimal(fraction: str) -> str:
    """소수부는 한 자리씩 읽는다. '4' → '점 사', '25' → '점 이오'."""
    return "점 " + "".join(_SINO_DIGITS[int(d)] if d != "0" else "영" for d in fraction)


_HANGUL_RE = re.compile(r"[가-힣]")

# 수사에 붙여 읽는 게 표준인 단위 — 띄우면 없던 쉼이 생겨 오히려 어색하다
_GLUED_UNITS = ("년", "월", "일", "분", "초", "원", "차", "층", "호", "위")

# 조사는 앞말에 붙는다 — '삼 에서'가 아니라 '삼에서'.
# '도'는 뺐다: 조사 '~도'와 단위 '온도 도'가 겹치는데, 후자를 띄우는 게 훨씬 중요하다
# (83.4도 → '팔십삼 점 사도'는 使徒로 읽힌다).
_PARTICLE_STARTS = ("에", "은", "는", "이", "가", "을", "를", "의", "와", "과", "로", "만")


def _read_number(match: re.Match[str], following: str) -> str:
    integer_text = match.group(1).replace(",", "")
    fraction = match.group(2)
    value = int(integer_text)

    # 소수·큰 수는 무조건 한자어. 고유어 단위명사가 뒤따르고 소수가 아닐 때만 고유어.
    if fraction is None and 1 <= value <= 99:
        counter = following.lstrip()
        if counter.startswith(_NATIVE_COUNTERS):
            # 수관형사와 단위명사는 띄어 쓴다 — '여섯 명', '스무 개'
            return native_korean(value, attributive=True) + " "

    out = sino_korean(value)
    if fraction:
        out += " " + _read_decimal(fraction)

    # 읽은 수사가 뒤 명사에 들러붙으면 합성기가 한 단어로 읽어 발음이 무너진다.
    # '2라운드'→'이라운드', '83.4도'→'팔십삼 점 사도'(使徒) 같은 사고를 막는다.
    # 다만 년·월·일·시 같은 시간/화폐 단위는 붙여 읽는 게 표준이라 예외로 둔다
    # ('이천이십육 년'처럼 띄면 없던 쉼이 생긴다).
    if (
        following[:1]
        and _HANGUL_RE.match(following[0])
        and not following.startswith(_GLUED_UNITS)
        and not following.startswith(_PARTICLE_STARTS)
    ):
        out += " "
    return out


def normalize_numbers(text: str) -> str:
    """텍스트 안의 아라비아 숫자를 한국어 읽는 소리로 바꾼다."""

    result: list[str] = []
    pos = 0
    for match in _NUMBER_RE.finditer(text):
        result.append(text[pos : match.start()])
        result.append(_read_number(match, text[match.end() : match.end() + 4]))
        pos = match.end()
    result.append(text[pos:])
    return "".join(result)


def apply_dictionary(text: str, entries: list[tuple[str, str]]) -> str:
    """사용자 발음 사전 적용. 긴 표기부터 치환해 부분 겹침을 막는다."""
    for source, target in sorted(entries, key=lambda e: len(e[0]), reverse=True):
        source = source.strip()
        if source:
            text = text.replace(source, target)
    return text


def normalize(
    text: str,
    *,
    dictionary: list[tuple[str, str]] | None = None,
    read_numbers: bool = True,
) -> str:
    """합성 직전 최종 정규화.

    순서가 중요하다 — 사용자 사전이 먼저다. 'HWAX 2.0' 을 '에이치왁스 이 점 영' 이 아니라
    통째로 '에이치왁스 투 포인트 오' 로 읽히고 싶을 수 있기 때문이다.
    """
    text = (text or "").strip()
    if not text:
        return ""

    if dictionary:
        text = apply_dictionary(text, dictionary)

    text = _RANGE_RE.sub("에서 ", text)
    # 양옆이 띄어진 대시는 삽입구 표시다. 합성기는 이걸 어떻게 읽을지 몰라 얼버무리므로
    # 쉼표로 바꿔 명시적인 쉼을 만든다. 단어 안 하이픈(A-1)은 건드리지 않는다.
    text = _INLINE_DASH_RE.sub(", ", text)
    for symbol, reading in _SYMBOL_MAP.items():
        text = text.replace(symbol, reading)

    if read_numbers:
        text = normalize_numbers(text)

    # 합성기가 헷갈리는 여백·중복 문장부호 정리
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\.{3,}", "…", text)
    return text.strip()
