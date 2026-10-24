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
    assert normalize_numbers("20살") == "스무 살"


def test_count_nouns_are_native_only_under_ten():
    """개·대·쌍·종·건은 1~9 만 고유어 — 사용자 대본의 읽는 법 규칙 (14개 → 십사 개)."""
    assert normalize_numbers("3건") == "세 건"
    assert normalize_numbers("9종") == "아홉 종"
    assert normalize_numbers("14개") == "십사 개"
    assert normalize_numbers("20개") == "이십 개"
    assert normalize_numbers("47개 가운데 43개가") == "사십칠 개 가운데 사십삼 개가"
    assert normalize_numbers("13건") == "십삼 건"


def test_months_are_sino():
    assert normalize_numbers("3개월") == "삼 개월"


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
    assert normalize_numbers("20개를") == "이십 개를"


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


# ── 영문 약어 · 단위 · 가운뎃점 · 읽는 법 ───────────────────────────────────


def test_uppercase_acronyms_are_spelled():
    """MeloTTS 는 사전에 없는 영문을 소리 없이 흘린다 — 글자 이름으로 바꿔 준다."""
    assert normalize("PLM 기준정보와 CAE 결과") == "피엘엠 기준정보와 씨에이이 결과"
    assert normalize("AI가 답합니다") == "에이아이가 답합니다"
    assert normalize("B책임") == "비책임"


def test_acronym_digits_are_read_as_numbers():
    assert normalize("모델 S26 출시") == "모델 에스이십육 출시"
    assert normalize("탭 S11") == "탭 에스십일"


def test_mixed_case_and_digit_first_words_are_left_alone():
    # 규칙으로 읽을 수 없는 것들 — 영문 글자가 남아 화면에 '영문 남음' 으로 드러난다
    from app.textnorm import latin_words

    out = normalize("Screw 체결과 3D 모델, A50s")
    assert {"Screw", "D", "A"} <= set(latin_words(out))


def test_units_after_numbers_are_read():
    assert normalize("0.5 mm 이상") == "영 점 오 밀리미터 이상"
    assert normalize("46dB 감소") == "사십육 데시벨 감소"
    assert normalize("2.4GHz 대역") == "이 점 사 기가헤르츠 대역"
    # 숫자가 앞에 없으면 단위가 아니다
    assert "mm" in normalize("mm 단위", read_numbers=True)


def test_plus_minus_and_degree():
    assert normalize("±1℃") == "플러스마이너스 일 도"
    assert normalize("45°") == "사십오 도"


def test_middle_dot_becomes_pause():
    assert normalize("기구·해석·신뢰성") == "기구, 해석, 신뢰성"
    assert normalize("구조 · 신뢰도") == "구조, 신뢰도"


def test_korean_rules_only_for_korean():
    assert normalize("PLM 2", language="en") == "PLM 이"  # 숫자 규칙은 기존대로, 약어는 그대로


def test_reading_pairs_apply_first():
    reading = "AI → 에이아이 · 6만 → 육만"
    assert normalize("AI가 6만 건을", reading=reading) == "에이아이가 육만 건을"
    # 씬 읽는 법이 전역 사전보다 앞선다
    out = normalize("HWAX 심의", reading="HWAX = 하드웨어 에이엑스", dictionary=[("HWAX", "에이치왁스")])
    assert out == "하드웨어 에이엑스 심의"


def test_parse_reading_pairs_formats():
    from app.textnorm import parse_reading_pairs

    assert parse_reading_pairs("AI → 에이아이 · 6만 → 육만") == [("AI", "에이아이"), ("6만", "육만")]
    assert parse_reading_pairs("HWAX = 하드웨어 에이엑스, UW = 유더블유") == [
        ("HWAX", "하드웨어 에이엑스"),
        ("UW", "유더블유"),
    ]
    assert parse_reading_pairs("「응력」 -> 응녁\n전·배면 => 전면과 배면") == [
        ("응력", "응녁"),
        ("전·배면", "전면과 배면"),
    ]
    assert parse_reading_pairs("발음 주의 메모뿐") == []
    assert parse_reading_pairs(None) == []


def test_latin_words_reports_leftovers():
    from app.textnorm import latin_words

    assert latin_words("스크루 Screw 와 Ultra, 다시 Screw") == ["Screw", "Ultra"]
    assert latin_words("모두 한글") == []
