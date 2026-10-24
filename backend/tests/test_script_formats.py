# 표·줄머리 타임코드·마크다운 제목 구간·읽는 법 형식 파싱 — 실제로 받아 본 형식을 합성 문장으로 흉내 냈다

from __future__ import annotations

import pytest

from app.script_parser import parse_script


def _cues(raw: str) -> list[tuple]:
    result = parse_script(raw)
    return [(s.target_start_sec, s.target_end_sec, s.title, s.text) for s in result.scenes]


def test_line_leading_ranges_without_blank_lines():
    raw = """0:00–0:07 커피 머신이 아침을 엽니다. 버튼 하나면 충분할까요?
0:07–0:15 지금까지는 원두를 갈고, 물을 데우고, 시간을 재는 수작업이었습니다.
0:15–0:19 이제, 말로 내립니다."""
    assert _cues(raw) == [
        (0.0, 7.0, None, "커피 머신이 아침을 엽니다. 버튼 하나면 충분할까요?"),
        (7.0, 15.0, None, "지금까지는 원두를 갈고, 물을 데우고, 시간을 재는 수작업이었습니다."),
        (15.0, 19.0, None, "이제, 말로 내립니다."),
    ]


def test_start_only_lines_under_section_lines():
    raw = """0:00 – 0:05 · 제목 (자막 없음) 화면: 로고
0:05 – 0:13 · 구성
0:05 이 과제는 세 장비 위에서 수행했습니다.
0:09 그라인더는 분쇄, 보일러는 온도, 펌프는 압력을 맡습니다.
0:13 – 0:18 · 이유
0:13 맛을 미리 맞추려면 추출이 실측을 따라야 합니다.
마지막 화면: 결론 문구"""
    assert _cues(raw) == [
        (5.0, 9.0, "구성", "이 과제는 세 장비 위에서 수행했습니다."),
        (9.0, 13.0, None, "그라인더는 분쇄, 보일러는 온도, 펌프는 압력을 맡습니다."),
        (13.0, None, "이유", "맛을 미리 맞추려면 추출이 실측을 따라야 합니다."),
    ]


def test_seconds_ranges_under_markdown_sections():
    raw = """# 녹음 대본 — 추출 개선 보고
영상: 추출.html · 총 20초
각 줄은 화면 자막과 1:1로 대응합니다.

## 1구간 · 표지 (0–6초)
**(0.3–6.0)** 추출 정합성 개선 경과를 보고합니다.

## 2구간 · 현상 (6–20초)
**(6.3–11.5)** 현상은 크레마 분리입니다.
**(11.5–16.0)** 1차 3잔, 2차 6잔에서 재현되었습니다."""
    assert _cues(raw) == [
        (0.3, 6.0, "1구간 · 표지", "추출 정합성 개선 경과를 보고합니다."),
        (6.3, 11.5, "2구간 · 현상", "현상은 크레마 분리입니다."),
        (11.5, 16.0, None, "1차 3잔, 2차 6잔에서 재현되었습니다."),
    ]


def test_bracketed_second_marks_and_script_reading_line():
    raw = """# 원인 추적 영상 대본
- 영상: 추적.mp4 · 길이 30초
- 읽는 법: ABC = 에이비씨, Brew Lab = 브루 랩
## 1. 오프닝 (0초~)
- [0초] 판매량이 전작보다 늘었습니다.
- [6.1초] ABC 시스템이 원인을 찾았습니다.
## 2. 분석 (14.7초~)
- [14.7초] Brew Lab 이 결과를 정리했습니다."""
    result = parse_script(raw)
    assert [(s.target_start_sec, s.target_end_sec, s.title) for s in result.scenes] == [
        (0.0, 6.1, "오프닝"),
        (6.1, 14.7, None),
        (14.7, None, "분석"),
    ]
    assert [s.number for s in result.scenes] == [1, None, 2]
    # 머리의 읽는 법은 본문에 그 말이 나오는 씬에만 붙는다
    assert [s.reading for s in result.scenes] == [None, "ABC → 에이비씨", "Brew Lab → 브루 랩"]


def test_heading_sections_with_numbered_sentences_and_notes():
    raw = """# 소개영상 v3 — 내레이션 대본
45초–1:45 구간이 어렵다는 피드백을 반영했습니다.
---
## 01 오프닝 (0:00–0:18.8) — v2와 동일
1. 이 앱은 잔량만 보고 절전을 켜는 앱이 아닙니다.
2. 미래 수요를 예측해 정책을 제안합니다.
## 02 문제 (0:18.8–0:45.2) — **전면 교체**
화면: 그래프가 흘러내린다
3. 밤 10시 40분, 잔량이 줄어듭니다.
> 바뀐 점: 나열을 줄였다"""
    assert _cues(raw) == [
        (0.0, 18.8, "오프닝", "이 앱은 잔량만 보고 절전을 켜는 앱이 아닙니다. 미래 수요를 예측해 정책을 제안합니다."),
        (18.8, 45.2, "문제", "밤 10시 40분, 잔량이 줄어듭니다."),
    ]
    assert [s.number for s in parse_script(raw).scenes] == [1, 2]


def test_heading_cues_skip_silent_parts_and_directions():
    raw = """## 파트1 — 본편 (00:00–00:22.5)
### 0. Intro (00:00–00:03) — 나레이션 없음
> (타이틀 화면)
### 1. Hook (00:03–00:10)
> 핀 배치의 경우의 수는 사실상 무한합니다.
### 2. Roadmap (00:13–00:22.5)
> 내년에는 도구화를 넓히겠습니다.
> (00:19–00:22.5 나레이션 없음 — 화면 유지)"""
    assert _cues(raw) == [
        (3.0, 10.0, "Hook", "핀 배치의 경우의 수는 사실상 무한합니다."),
        # 뒤의 무음 구간에서 끝이 잘린다
        (13.0, 19.0, "Roadmap", "내년에는 도구화를 넓히겠습니다."),
    ]


def test_title_dash_time_lines_with_inline_numbers():
    raw = """Platform — 0:00
본 과제는 세 플랫폼을 연결해 수행했습니다.
질의부터 실행까지 한 흐름입니다.
Stakes — 0:21 4. 정확도 확보가 선행 조건입니다. 5. 모델은 이미 쌓여 있습니다."""
    assert _cues(raw) == [
        (0.0, 21.0, "Platform", "본 과제는 세 플랫폼을 연결해 수행했습니다. 질의부터 실행까지 한 흐름입니다."),
        (21.0, None, "Stakes", "정확도 확보가 선행 조건입니다. 모델은 이미 쌓여 있습니다."),
    ]


def test_markdown_tables_with_blank_lines_between_rows():
    raw = """| 항목 | 내용 |

|---|---|

| 영상 파일 | 데모.mp4 |

### 검증

| 번호 | 시간 | 대본 | 길이 · 속도 |

|---:|:---:|---|:---:|

| 1 | 0:00 ~ 0:08 | 기능 검증은 설명회 이력으로 수행했습니다. | 8초 · 4.4 |

| 2 | 0:08 ~ 0:18 | 설명회에서 변경을 공유합니다. | 10초 · 4.8 |

### 결과

| 번호 | 시간 | 대본 | 길이 · 속도 |
|---:|:---:|---|:---:|
| 3 | 0:18 ~ 0:32 | 결과는 뚜렷하게 갈렸습니다. | 14초 · 3.8 |"""
    result = parse_script(raw)
    assert [(s.number, s.target_start_sec, s.target_end_sec, s.text) for s in result.scenes] == [
        (1, 0.0, 8.0, "기능 검증은 설명회 이력으로 수행했습니다."),
        (2, 8.0, 18.0, "설명회에서 변경을 공유합니다."),
        (3, 18.0, 32.0, "결과는 뚜렷하게 갈렸습니다."),
    ]


def test_tab_separated_sheet_with_start_end_and_reading_columns():
    rows = [
        ["번호", "장면", "구간", "나레이션(원고)", "읽는 법(숫자 · 영문)", "시작", "끝", "목표 길이(초)", "시작(초)", "발음 주의"],
        ["1", "S01 오프닝", "1", "AI가 데이터를 연결합니다.", "AI → 에이아이", "00:00.3", "00:07.6", "7.3", "0.3", ""],
        ["2", "", "2", "6만 건을 정리했습니다.", "6만 → 육만", "00:07.6", "00:12.5", "4.9", "7.6", "「건」 또렷하게"],
        ["합계", "", "", "", "", "", "", "12.2", "", ""],
    ]
    raw = "\n".join("\t".join(r) for r in rows)
    result = parse_script(raw)
    assert [(s.number, s.title, s.target_start_sec, s.target_end_sec, s.reading) for s in result.scenes] == [
        (1, "S01 오프닝", 0.3, 7.6, "AI → 에이아이"),
        (2, None, 7.6, 12.5, "6만 → 육만"),
    ]


def test_flattened_sheet_paste_with_fullwidth_empty_cells():
    # 표 칸마다 줄이 바뀌어 붙여넣어진 형태 — 빈 칸은 전각 공백 한 줄로 온다
    header = ["번호", "장면", "나레이션(원고)", "읽는 법", "시작", "끝"]
    rows = [
        ["1", "S01 오프닝", "AI가 기준을 맞춥니다.", "AI → 에이아이", "00:00.3", "00:07.6"],
        ["2", "　", "흩어진 데이터를 묶습니다.", "　", "00:07.6", "00:12.5"],
    ]
    cells = header + [c for r in rows for c in r] + ["합계", "12.2"]
    raw = "안내\n멘트별 시간 — 원고 R1(2문장)\n" + "\n\n".join(cells)
    result = parse_script(raw)
    assert [(s.title, s.text, s.target_start_sec, s.reading) for s in result.scenes] == [
        ("S01 오프닝", "AI가 기준을 맞춥니다.", 0.3, "AI → 에이아이"),
        (None, "흩어진 데이터를 묶습니다.", 7.6, None),
    ]


def test_flattened_storyboard_with_vo_marker_and_durations():
    raw = """01
무한한 방향
0:00
7초
화면
기기가 링을 따라 낙하
V/O
제품이 떨어지는 방향은 사실상 무한합니다.
02
수작업의 한계
0:07
8초
화면
작업 단계 카드
V/O
지금까지는 전부 수작업이었습니다."""
    assert _cues(raw) == [
        (0.0, 7.0, None, "제품이 떨어지는 방향은 사실상 무한합니다."),
        (7.0, 15.0, None, "지금까지는 전부 수작업이었습니다."),
    ]


def test_block_format_with_length_memo_and_document_title():
    raw = """커피 머신 소개영상 — 내레이션 대본 (0분 20초 · 2씬)
01 오프닝 (0:00–0:08 / 8초) 질문 하나가 한 잔이 되기까지.
02 문제 (0:08–0:20 / 12초) 원두가 3주째 남습니다."""
    assert _cues(raw) == [
        (0.0, 8.0, "오프닝", "질문 하나가 한 잔이 되기까지."),
        (8.0, 20.0, "문제", "원두가 3주째 남습니다."),
    ]


def test_block_format_strips_dash_between_timecode_and_body():
    raw = """Hook [0:00–0:07] — 핀 배치의 경우의 수는 무한합니다.
Manual [0:07–0:15] — 확인 하나에 수 시간이 걸렸습니다."""
    assert _cues(raw) == [
        (0.0, 7.0, "Hook", "핀 배치의 경우의 수는 무한합니다."),
        (7.0, 15.0, "Manual", "확인 하나에 수 시간이 걸렸습니다."),
    ]


@pytest.mark.parametrize(
    "line",
    ["3초 만에 결과가 나옵니다.", "1. 첫째 문장입니다.", "2026-10-24 기준입니다.", "3-4개 정도입니다."],
)
def test_ordinary_narration_lines_are_not_cues(line):
    raw = f"{line}\n두 번째 줄입니다."
    assert all(s.target_start_sec is None for s in parse_script(raw).scenes)
