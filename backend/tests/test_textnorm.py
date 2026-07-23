# 숫자 한글 읽기 · 발음 사전 정규화

from __future__ import annotations

import pytest

from app.textnorm import native_korean, normalize, normalize_numbers, sino_korean


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "영"),
        (1, "일"),
        (6, "육"),
        (10, "십"),
        (11, "십일"),
        (20, "이십"),
        (83, "팔십삼"),
        (100, "백"),
        (1000, "천"),
        (1234, "천이백삼십사"),
        (10000, "만"),
        (20250, "이만이백오십"),
        (100000000, "억"),
    ],
)
def test_sino_korean(value, expected):
    assert sino_korean(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(1, "하나"), (2, "둘"), (6, "여섯"), (10, "열"), (20, "스물"), (21, "스물하나"), (99, "아흔아홉")],
)
def test_native_korean(value, expected):
    assert native_korean(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(1, "한"), (2, "두"), (3, "세"), (4, "네"), (20, "스무"), (21, "스물한")],
)
def test_native_korean_attributive(value, expected):
    assert native_korean(value, attributive=True) == expected


def test_decimal_is_read_digit_by_digit():
    # 붙여 쓰면 '사도'(使徒)로 읽힌다 — 단위 앞은 띄어야 한다
    assert normalize_numbers("83.4도") == "팔십삼 점 사 도"
    assert normalize_numbers("2.25") == "이 점 이오"


def test_native_counter_uses_native_numerals():
    assert normalize_numbers("6명이 모였다") == "여섯 명이 모였다"
    assert normalize_numbers("3개") == "세 개"
    assert normalize_numbers("20개") == "스무 개"


def test_non_counter_uses_sino_numerals():
    # 수사가 뒤 명사에 들러붙으면 합성기가 한 단어로 읽어 발음이 무너진다
    assert normalize_numbers("2라운드") == "이 라운드"
    assert normalize_numbers("6인") == "육 인"


def test_time_units_stay_glued():
    """년·월·일·분은 붙여 읽는 게 표준이라 띄우지 않는다 (없던 쉼이 생긴다)."""
    assert normalize_numbers("2026년") == "이천이십육년"
    assert normalize_numbers("2026년 7월 23일") == "이천이십육년 칠월 이십삼일"
    assert normalize_numbers("1,200원") == "천이백원"


def test_hour_is_native_but_minute_is_sino():
    """한국어 시간 관습 — 시는 고유어(세 시), 분은 한자어(삼십 분)."""
    assert normalize_numbers("오후 3시 30분") == "오후 세 시 삼십분"


def test_particles_stay_attached():
    """조사는 앞말에 붙는다 — '삼 에서'가 아니라 '삼에서'."""
    assert normalize_numbers("3에서 5개") == "삼에서 다섯 개"
    assert normalize_numbers("20개를") == "스무 개를"


def test_spaced_dash_becomes_comma():
    """삽입구 대시는 합성기가 얼버무린다 — 쉼표로 바꿔 명시적인 쉼을 만든다."""
    assert normalize("되기까지 — 플랫폼입니다") == "되기까지, 플랫폼입니다"
    # 단어 안 하이픈은 건드리지 않는다
    assert "A-" in normalize("모델 A-1 시험", read_numbers=False)


def test_comma_grouped_numbers():
    assert normalize_numbers("1,234") == "천이백삼십사"


def test_dictionary_applied_before_numbers():
    text = normalize("HWAX 협업진단", dictionary=[("HWAX", "에이치왁스")])
    assert text == "에이치왁스 협업진단"


def test_longer_dictionary_key_wins():
    entries = [("AI", "에이아이"), ("AI Hub", "에이아이 허브")]
    assert normalize("AI Hub 접속", dictionary=entries) == "에이아이 허브 접속"


def test_symbols_are_read():
    assert "퍼센트" in normalize("50% 감소")
    assert "도" in normalize("83℃")


def test_range_tilde_becomes_eseo():
    assert normalize("3~5개") == "삼에서 다섯 개"


def test_read_numbers_can_be_disabled():
    assert normalize("83.4도", read_numbers=False) == "83.4도"


def test_empty_input():
    assert normalize("") == ""
    assert normalize("   ") == ""


def test_whitespace_and_ellipsis_are_tidied():
    assert normalize("가   나") == "가 나"
    assert normalize("그리고....") == "그리고…"
