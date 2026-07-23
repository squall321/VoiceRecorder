# 스크립트 파서 — 사용자 실제 형식과 폴백 형식을 모두 커버한다

from __future__ import annotations

import pytest

from app.script_parser import chunk_text, format_timecode, parse_script, parse_timecode

REAL_SCRIPT = """01 오프닝 (0:00–0:08) "질문 하나가 의사결정문이 되기까지 — HWAX 협업진단 플랫폼. 방열 난제를 맡은 B책임의 하루를 따라가 봅니다."

02 문제 배정 (0:08–0:19) "신제품 초기안의 최고 온도는 83.4도. 허용 기준을 넘겼습니다. 히트파이프, 베이퍼 챔버, 그라파이트 — 열, 기구, 재료, 배치, 신뢰성, 원가까지. 여섯 분야가 얽힌 문제가 B책임 한 사람에게 떨어졌습니다."

03 사람 회의 (0:19–0:31) "기존 방식이라면, 전문가 여섯 명의 일정을 맞추는 데만 몇 주."

10 아웃트로 (1:42–1:50) "HWAX 협업진단 플랫폼. 질문을 던지세요 — 전문가 회의가 열립니다."
"""


def test_parses_user_script_format():
    result = parse_script(REAL_SCRIPT)

    assert result.structured is True
    assert len(result.scenes) == 4

    first = result.scenes[0]
    assert first.number == 1
    assert first.title == "오프닝"
    assert first.target_start_sec == 0.0
    assert first.target_end_sec == 8.0
    assert first.target_duration_sec == 8.0
    assert first.text.startswith("질문 하나가 의사결정문이 되기까지")
    assert '"' not in first.text

    last = result.scenes[-1]
    assert last.number == 10
    assert last.title == "아웃트로"
    assert last.target_start_sec == 102.0  # 1:42
    assert last.target_end_sec == 110.0


def test_en_dash_and_hyphen_and_tilde_all_parse():
    for dash in ["–", "-", "—", "~"]:
        result = parse_script(f'01 씬 (0:00{dash}0:05) "본문입니다."')
        assert result.scenes[0].target_end_sec == 5.0, dash


DURATION_SCRIPT = """01 오프닝 (8초, ~32자) "첫 씬입니다."

02 문제 배정 (11초, ~46자) "둘째 씬입니다."

03 전환 (7초) "셋째 씬입니다."
"""


def test_duration_only_format_accumulates_timecodes():
    """'(8초)' 처럼 길이만 적힌 형식 — 시작 시각을 앞에서부터 누적해 채운다."""
    result = parse_script(DURATION_SCRIPT)

    assert result.structured is True
    assert len(result.scenes) == 3
    assert [s.target_start_sec for s in result.scenes] == [0.0, 8.0, 19.0]
    assert [s.target_end_sec for s in result.scenes] == [8.0, 19.0, 26.0]
    assert [s.target_duration_sec for s in result.scenes] == [8.0, 11.0, 7.0]


def test_duration_annotation_is_stripped_from_title():
    result = parse_script(DURATION_SCRIPT)
    assert [s.title for s in result.scenes] == ["오프닝", "문제 배정", "전환"]
    assert result.scenes[0].text == "첫 씬입니다."


@pytest.mark.parametrize("header", ["(8초)", "(약 8초)", "(8s)", "(8 sec)", "(8초, ~32자)"])
def test_duration_variants(header):
    result = parse_script(f'01 오프닝 {header} "본문입니다."')
    assert result.scenes[0].target_duration_sec == 8.0
    assert result.scenes[0].title == "오프닝"


def test_explicit_timecode_wins_over_duration_and_anchors_the_rest():
    """두 형식이 섞이면 명시된 타임코드를 기준으로 이후 누적이 이어진다."""
    raw = '01 가 (5초) "하나."\n\n02 나 (0:30–0:40) "둘."\n\n03 다 (6초) "셋."'
    scenes = parse_script(raw).scenes

    assert (scenes[0].target_start_sec, scenes[0].target_end_sec) == (0.0, 5.0)
    assert (scenes[1].target_start_sec, scenes[1].target_end_sec) == (30.0, 40.0)
    assert (scenes[2].target_start_sec, scenes[2].target_end_sec) == (40.0, 46.0)


def test_falls_back_to_paragraph_split():
    raw = "첫 문단입니다.\n\n두 번째 문단입니다.\n\n세 번째 문단입니다."
    result = parse_script(raw)

    assert result.structured is False
    assert [s.text for s in result.scenes] == [
        "첫 문단입니다.",
        "두 번째 문단입니다.",
        "세 번째 문단입니다.",
    ]
    assert all(s.number is None for s in result.scenes)


def test_numbered_lines_without_blank_lines():
    raw = '01 오프닝 "첫 씬."\n02 전개 "둘째 씬."\n03 결말 "셋째 씬."'
    result = parse_script(raw)

    assert len(result.scenes) == 3
    assert [s.number for s in result.scenes] == [1, 2, 3]
    assert result.scenes[1].text == "둘째 씬."


def test_multiline_body_is_joined():
    raw = '01 오프닝 (0:00–0:08) "첫 줄\n이어지는 둘째 줄."'
    result = parse_script(raw)

    assert len(result.scenes) == 1
    assert result.scenes[0].text == "첫 줄 이어지는 둘째 줄."


def test_inner_quotes_survive_outer_stripping():
    """본문이 인용으로 시작해도 여는 따옴표가 살아 있어야 한다 (짝 없는 따옴표 방지)."""
    result = parse_script("""01 자체교정 (16초) "'그라파이트로 충분하다'던 초기 계산." """)
    text = result.scenes[0].text

    assert text == "'그라파이트로 충분하다'던 초기 계산."
    assert text.count("'") == 2


def test_body_without_quotes():
    result = parse_script("01 오프닝 (0:00–0:08) 따옴표 없는 본문입니다.")
    scene = result.scenes[0]

    assert scene.title == "오프닝"
    assert scene.text == "따옴표 없는 본문입니다."


def test_empty_script_yields_nothing():
    assert parse_script("").scenes == []
    assert parse_script("   \n\n  ").scenes == []


def test_parentheses_inside_body_are_not_timecodes():
    result = parse_script('01 오프닝 (0:00–0:08) "본문 (0:99–9:99) 안의 괄호."')
    scene = result.scenes[0]

    assert scene.target_end_sec == 8.0
    assert "(0:99–9:99)" in scene.text


@pytest.mark.parametrize(
    "value,expected",
    [("0:00", 0.0), ("0:08", 8.0), ("1:06", 66.0), ("01:02:03", 3723.0), ("0:08.5", 8.5)],
)
def test_parse_timecode(value, expected):
    assert parse_timecode(value) == expected


def test_format_timecode_srt():
    assert format_timecode(0.0, millis=True) == "00:00:00,000"
    assert format_timecode(66.5, millis=True) == "00:01:06,500"
    assert format_timecode(3723.25, millis=True) == "01:02:03,250"


def test_format_timecode_display():
    assert format_timecode(8.0) == "0:08"
    assert format_timecode(102.0) == "1:42"
    assert format_timecode(3723.0) == "1:02:03"


def test_chunk_text_keeps_short_text_intact():
    assert chunk_text("짧은 문장입니다.", 300) == ["짧은 문장입니다."]


def test_chunk_text_splits_on_sentence_boundaries():
    text = " ".join(["가나다라마바사아자차 문장입니다."] * 30)
    chunks = chunk_text(text, 120)

    assert len(chunks) > 1
    assert all(len(c) <= 120 for c in chunks)
    # 글자가 하나도 사라지면 안 된다
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_chunk_text_force_splits_a_single_long_sentence():
    text = "가" * 500
    chunks = chunk_text(text, 100)

    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks) == text
