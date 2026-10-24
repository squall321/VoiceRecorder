# 표·줄머리 타임코드·마크다운 제목 구간·자막 파일 형식의 대본에서 큐(시작·끝·제목·본문·읽는 법)를 뽑는다

"""기존 블록 파서(`01 제목 (0:00–0:08) "본문"`)가 못 읽는 형식을 맡는다.

실제로 받아 본 대본 형식들:
  - 줄머리 타임코드      `0:00–0:07 본문` · `0:05 본문` · `**(0.3–6.0)** 본문` · `- [6.1초] 본문`
  - 구간 머리줄 + 큐     `0:05 – 0:13 · 플랫폼 구도` 다음 줄부터 `0:05 본문`
  - 제목 — 시각          `Platform — 0:00` 다음 줄들이 본문, `Stakes — 0:21 4. 문장 5. 문장`
  - 마크다운 제목 구간   `## 01 오프닝 (0:00–0:18.8)` 아래 문장들 / `## 1구간 (0–6초)` 아래 큐들
  - 씬 머리줄            `01 오프닝 (0:00–0:08)` 한 줄 아래에 본문 — 제목 구간과 같게 다룬다
  - 표                   마크다운 `| 번호 | 시간 | 대본 |`, 엑셀에서 복사한 탭 구분 표(칸 안 줄바꿈 포함)
  - 자막 파일            SRT · VTT 를 그대로 붙여넣은 것
  - 읽는 법              표의 「읽는 법」 열, `읽는 법: A = 가, B = 나` 줄(아래 목록 줄 포함)

결과는 dict 리스트다. ParsedScene 변환과 따옴표 정리는 script_parser 가 한다(순환 임포트 방지).
"""

from __future__ import annotations

import csv
import io
import re

from .textnorm import parse_reading_pairs

_DASH = r"[-–—−~]"
# 초 자리는 두 자리 — '1:1 맞춤', '24:7 운영', '3:1 승리' 같은 비율을 시각으로 오인하지 않는다
_COLON_TC = r"\d{1,3}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?"
_SEC_TC = r"\d{1,4}(?:[.,]\d{1,3})?\s*(?:초|s(?![A-Za-z]))"
_BARE = r"\d{1,4}(?:[.,]\d{1,3})?"
_TIME = rf"(?:{_COLON_TC}|{_SEC_TC})"
_ANY = rf"(?:{_TIME}|{_BARE})"

# 줄 앞의 목록·인용·강조 기호 — '- ', '> ', '**'
_PREFIX_RE = re.compile(r"^(?:\s*(?:[-*+•▪>]|\*\*|__)\s*)*")
# 줄머리 범위 — 괄호는 있어도 없어도 된다. 끝이 비면 열린 구간('(0초~)')
_LEAD_RANGE_RE = re.compile(
    rf"^(?P<open>[\[(])?\s*(?P<s>{_ANY})\s*{_DASH}\s*(?P<e>{_ANY})?\s*(?P<close>[\])])?"
)
# 줄머리 시작 시각 하나 — 콜론형은 그냥, 초 단위는 괄호 안일 때만('[6.1초]').
# '3초 만에 끝납니다' 같은 본문을 큐로 오인하지 않으려는 제한이다.
_LEAD_START_RE = re.compile(rf"^(?:\[\s*(?P<b>{_TIME})\s*\]|\(\s*(?P<p>{_TIME})\s*\)|(?P<s>{_COLON_TC})(?![\d:]))")
# 'Platform — 0:00' / '01 Platform — 0:00' / 'Stakes — 0:21 4. 문장'
_TITLE_DASH_RE = re.compile(
    rf"^(?P<title>(?:\d{{1,3}}\s+)?[^\s\d\[(#|][^\n]{{0,40}}?)\s+[—–-]\s+(?P<s>{_COLON_TC})(?![\d:])(?P<rest>.*)$"
)
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<body>.+)$")
# 제목 안의 시각 — 괄호 범위('(0:00–0:18.8)' '(0–6초)' '(22.5초~)') 또는 괄호 속 콜론 시각 하나.
# 괄호 끝의 길이 메모('/ 8초', ' 8초')는 받아서 버린다.
_HEAD_RANGE_RE = re.compile(rf"[\[(]\s*(?P<s>{_ANY})\s*{_DASH}\s*(?P<e>{_ANY})?\s*(?:[/·,|\s][^)\]]*)?[\])]")
_HEAD_START_RE = re.compile(rf"[\[(]\s*(?P<s>{_COLON_TC})\s*[\])]")
# 씬 머리줄 — '01 오프닝 (0:00–0:08)', 'S02 문제', '[씬 2] 문제', '02 문제' (본문 없이 그 줄로 끝난다)
_SCENE_HEADER_RE = re.compile(
    rf"^(?P<pre>\[\s*)?(?P<kind>씬|장면|Scene|SCENE|scene|S)?\s*(?P<num>\d{{1,3}})\s*\]?[.)]?\s+"
    rf"(?P<title>[^\s\"“'‘「(\[][^\"“'‘「(\[]{{0,30}}?)\s*"
    rf"(?P<time>[\[(]\s*{_ANY}\s*(?:{_DASH}\s*(?:{_ANY})?)?\s*(?:[/·,|\s][^)\]]*)?[\])])?\s*$"
)
# 제목 + 괄호 시각 — 'Manual [0:08–0:19]' (그 줄로 끝나면 머리줄) / 'Hook [0:00–0:07] — 본문' (큐)
_TITLE_RANGE_RE = re.compile(
    rf"^(?P<title>[^\d\s\[(#|][^\[(\n]{{0,25}}?)\s*[\[(]\s*(?P<s>{_COLON_TC})\s*(?:{_DASH}\s*(?P<e>{_COLON_TC})?)?\s*[\])]"
    rf"\s*(?:[—–\-:]\s*(?P<text>.*))?$"
)

_RULE_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,}|={3,})$")
_DIRECTION_RE = re.compile(r"^[(\[].*[)\]]$")  # (타이틀 화면) 같은 화면 지시
# 읽지 않는 메모 줄 — 아는 이름만 지운다('결론: …' 같은 본문까지 지우지 않게)
_NOTE_LABEL_RE = re.compile(
    r"^(?:마지막\s?화면|화면\s?전환|화면|바뀐\s?점|참고|메모|비고|주의|영상|파일|길이|구성|연출|촬영|자막|효과음|음악"
    r"|BGM|SFX|CG|그래픽|note)\s*[:：]",
    re.IGNORECASE,
)
# 본문 앞에 붙는 낭독 표시 — 떼고 나머지를 읽는다('나레이션: 첫 문장', '**NA:** …', 'V/O: …')
_NARRATION_LABEL_RE = re.compile(
    r"^(?:\*\*)?\s*(?:나레이션|내레이션|NA|N\.A\.|V/O|V\.O\.?|VO|음성|대사|멘트)\s*(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*",
    re.IGNORECASE,
)
# 줄 하나로 선 낭독 표시 — 앞은 화면 설명, 뒤가 본문
_VO_RE = re.compile(r"^(?:V/?O|V\.O\.?|VO|NA|나레이션|내레이션|음성)$", re.IGNORECASE)
_NUMBER_ONLY_RE = re.compile(r"^\d{1,3}$")
_DURATION_ONLY_RE = re.compile(rf"^(?P<d>{_SEC_TC})$")
_INLINE_NUM_RE = re.compile(r"(?:^|(?<=[.!?。…]\s))\d{1,3}\.\s+")
# '나레이션 없음' 만 비운다 — '무음 모드', '앞 2초 무음' 같은 말까지 지우지 않게
_NO_NARRATION_RE = re.compile(r"(?:나레이션|내레이션)\s*없음")
_HEAD_NUMBER_RE = re.compile(r"^(?P<num>\d{1,3})[.)]?\s+(?P<title>\S.*)$")
_NOTE_TAIL_RE = re.compile(r"\s+[—–]\s+.*$")
_SENTENCE_END_RE = re.compile(r"[.!?。…]")

_READING_LINE_RE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:\*\*)?\s*(?:읽는\s?법|읽기)\s*(?:\*\*)?\s*[:：]\s*(?P<pairs>.*)$"
)
# '읽는 법:' 아래로 이어지는 목록 줄 — '- HWAX = 하드웨어 에이엑스'
_READING_ITEM_RE = re.compile(r"^\s*(?:[-*•]\s*)?(?P<pair>\S.*(?:→|->|=>|=).*)$")

# 자막 파일 — '00:00:05,000 --> 00:00:08,000' (VTT 는 '.' · 시 생략 가능)
_SUB_TIME = r"(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}"
_SUB_LINE_RE = re.compile(rf"^\s*(?P<s>{_SUB_TIME})\s*-->\s*(?P<e>{_SUB_TIME})")
_SUB_TAG_RE = re.compile(r"<[^>]+>|\{\\[^}]*\}")


def seconds_of(token: str) -> float:
    """'1:06.5' → 66.5, '6.1초' → 6.1, '0.3' → 0.3"""
    value = re.sub(r"\s*(?:초|s)$", "", token.strip()).replace(",", ".")
    total = 0.0
    for part in value.split(":"):
        total = total * 60 + float(part)
    return total


def _is_real_time(token: str | None) -> bool:
    return bool(token) and (":" in token or bool(re.search(r"(?:초|s)$", token.strip())))


def _strip_inline(text: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = text.replace("**", "").replace("__", "").replace("　", " ")
    return " ".join(text.split())


def _range(start: float, end: float | None) -> tuple[float, float | None]:
    # 거꾸로 적힌 범위('0:08–0:00')는 끝을 버린다 — 시작만 믿는다
    return start, (end if end is None or end > start else None)


# ── 본문 줄 정리 (블록 파서도 쓴다) ─────────────────────────────────────────


def is_note_line(line: str) -> bool:
    """읽지 않는 줄 — 화면 지시 '(타이틀 화면)', '화면: …' 같은 메모, '※ …'."""
    line = line.strip()
    return bool(_DIRECTION_RE.match(line) or _NOTE_LABEL_RE.match(line) or line.startswith("※"))


def strip_narration_label(line: str) -> str:
    return _NARRATION_LABEL_RE.sub("", line.strip(), count=1)


# ── 읽는 법 줄 ──────────────────────────────────────────────────────────────


def extract_reading_lines(raw: str) -> tuple[str, list[tuple[str, str]]]:
    """대본 머리의 `읽는 법: HWAX = 하드웨어 에이엑스, UW = 유더블유` 줄을 떼어 쌍으로 돌려준다."""
    pairs: list[tuple[str, str]] = []
    kept: list[str] = []
    in_list = False  # '읽는 법:' 이 빈 채로 끝나면 다음 줄들이 목록이다
    for line in raw.split("\n"):
        m = _READING_LINE_RE.match(line)
        if m:
            pairs.extend(parse_reading_pairs(m.group("pairs")))
            in_list = not m.group("pairs").strip()
            continue
        if in_list:
            item = _READING_ITEM_RE.match(line)
            if item:
                pairs.extend(parse_reading_pairs(item.group("pair")))
                continue
            in_list = False
        kept.append(line)
    return "\n".join(kept), pairs


def format_pairs(pairs: list[tuple[str, str]]) -> str | None:
    seen: dict[str, str] = {}
    for source, target in pairs:
        seen.setdefault(source, target)
    return " · ".join(f"{s} → {t}" for s, t in seen.items()) or None


# ── 자막 파일 (SRT · VTT) ───────────────────────────────────────────────────


def parse_subtitles(raw: str) -> list[dict] | None:
    """SRT·VTT 를 그대로 붙여넣은 경우 — 시각 줄 아래 빈 줄까지가 한 큐다."""
    lines = raw.split("\n")
    if sum(1 for line in lines if _SUB_LINE_RE.match(line)) < 2:
        return None
    cues: list[dict] = []
    current: dict | None = None
    for line in lines:
        m = _SUB_LINE_RE.match(line)
        if m:
            if current and current["lines"]:
                cues.append(current)
            start, end = _range(seconds_of(m.group("s")), seconds_of(m.group("e")))
            current = {"start": start, "end": end, "lines": []}
            continue
        stripped = line.strip()
        if current is None or not stripped:
            if current and current["lines"]:
                cues.append(current)
                current = None
            continue
        if not current["lines"] and _NUMBER_ONLY_RE.match(stripped):
            continue
        current["lines"].append(_SUB_TAG_RE.sub("", stripped))
    if current and current["lines"]:
        cues.append(current)
    result = [
        {"start": c["start"], "end": c["end"], "title": None, "number": None,
         "text": _strip_inline(" ".join(c["lines"])), "reading": None}
        for c in cues
    ]
    return result if len(result) >= 2 else None


# ── 표 (마크다운 · 탭 구분) ─────────────────────────────────────────────────

_H_TEXT = ("나레이션", "내레이션", "대본", "원고", "멘트", "스크립트", "자막")
_H_TEXT_EN = ("narration", "script", "text", "voiceover")
_H_READING = ("읽는", "읽기")
_H_TIME = ("시간", "타임코드", "타임", "구간 시각", "시각")
_H_TIME_EN = ("time", "tc", "timecode")
_H_START = ("시작",)
_H_START_EN = ("start", "in")
_H_END = ("끝", "종료")
_H_END_EN = ("end", "out")
_H_TITLE = ("장면", "씬", "제목", "구간", "섹션")
_H_TITLE_EN = ("scene", "title", "section")
_H_NUMBER = ("번호",)
_H_NUMBER_EN = ("no", "#", "no.")
# 이런 말이 붙은 열은 그 열의 '값'이 아니라 부가 정보다 — '나레이션 글자수', '소요 시간', '대본 메모'
_H_PENALTY = ("글자", "자수", "개수", "길이", "메모", "비고", "소요", "목표", "분량", "속도", "주의", "확인")


def _header_score(header: str, keyword: str) -> int:
    h = header.lower().replace(" ", "")
    k = keyword.lower().replace(" ", "")
    base = re.sub(r"\(.*?\)", "", h)
    if k not in h:
        return 0
    score = 3 if base == k else 2 if base.startswith(k) else 1
    if any(p in base for p in _H_PENALTY if p not in k):
        score -= 3
    return score


def _find_col(
    header: list[str], korean: tuple[str, ...], english: tuple[str, ...], exclude: set[int] = frozenset()
) -> int | None:
    """머리줄에서 그 역할의 열 — 이름이 정확히 같은 열 > 그 말로 시작하는 열 > 그 말이 든 열.
    '나레이션 글자수'·'소요 시간'처럼 부가 정보 열은 깎아서 본 열을 고른다."""
    best: tuple[int, int] | None = None
    for i, h in enumerate(header):
        if i in exclude:
            continue
        score = max((_header_score(h, k) for k in korean), default=0)
        for k in english:
            if re.fullmatch(rf"\W*{re.escape(k)}\W*", h.lower()):
                score = max(score, 3)
        if score > 0 and (best is None or score > best[0]):
            best = (score, i)
    return best[1] if best else None


def _time_cell(cell: str, *, lenient: bool) -> tuple[float | None, float | None]:
    """셀 하나에서 (시작, 끝). lenient=True(시간 열로 확인됨)면 맨 숫자도 초로 받는다."""
    cell = _strip_inline(cell)
    if not cell:
        return None, None
    m = re.fullmatch(rf"(?P<s>{_ANY})\s*{_DASH}\s*(?P<e>{_ANY})?", cell)
    if m and (lenient or _is_real_time(m.group("s")) or _is_real_time(m.group("e"))):
        end = seconds_of(m.group("e")) if m.group("e") else None
        return _range(seconds_of(m.group("s")), end)
    single = _ANY if lenient else _TIME
    if re.fullmatch(single, cell):
        return seconds_of(cell), None
    return None, None


def _markdown_cells(line: str) -> list[str]:
    # 이스케이프된 '\|' 는 칸 구분자가 아니다
    inner = line.strip().strip("|")
    return [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", inner)]


def _table_rows(raw: str) -> list[list[list[str]]]:
    """연속된 표 줄을 블록으로 묶는다. 빈 줄은 블록을 끊지 않는다(붙여넣기가 줄을 띄우곤 한다).

    탭 구분 표는 csv 로 읽는다 — 엑셀은 칸 안에 줄바꿈이 있으면 그 칸을 따옴표로 감싸 내보낸다.
    """
    blocks: list[list[list[str]]] = []
    current: list[list[str]] = []

    def flush() -> None:
        nonlocal current
        if current:
            blocks.append(current)
            current = []

    if "\t" in raw and not any(line.strip().startswith("|") for line in raw.split("\n")):
        for row in csv.reader(io.StringIO(raw), delimiter="\t"):
            cells = [c.strip() for c in row]
            if len(cells) < 2:
                if any(c for c in cells):
                    flush()
                continue
            current.append(cells)
        flush()
        return blocks

    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("|") and stripped.count("|") >= 2:
            cells = _markdown_cells(stripped)
        else:
            flush()
            continue
        if all(re.fullmatch(r":?-{2,}:?", c) or not c for c in cells):
            continue  # 마크다운 구분 줄
        current.append(cells)
    flush()
    return blocks


_HEADER_CELL_RE = re.compile(r"^[^\d:.!?]{1,14}$")
_KNOWN_HEADERS = {
    "번호", "장면", "씬", "구간", "제목", "나레이션", "내레이션", "대본", "원고", "자막", "읽는법",
    "시작", "끝", "종료", "시간", "목표길이", "길이", "발음주의", "비고", "메모", "화면",
}


def _is_known_header(cell: str) -> bool:
    base = re.sub(r"\(.*?\)", "", cell).replace(" ", "")
    return base in _KNOWN_HEADERS


def _flattened_rows(raw: str) -> list[list[str]] | None:
    """엑셀 표를 붙여넣을 때 칸마다 줄이 바뀐 형태 — 헤더 칸 N개 뒤로 N칸씩 행이 이어진다.

    빈 칸은 전각 공백(　) 한 줄로 온다. 그 줄을 지우면 칸이 밀리므로 ASCII 공백만 빈 줄로 본다.
    헤더는 짧은 이름 칸이 3개 이상 이어지고 그중 둘 이상이 아는 열 이름이어야 하며(본문·시각 열 포함),
    묶은 행의 대부분에서 시작 칸이 실제 시각이어야 한다 — 짧은 줄이 많은 콘티를 표로 오인하지 않게.
    """
    cells = [line.strip(" \t") for line in raw.split("\n") if line.strip(" \t")]
    i = 0
    while i < len(cells):
        j = i
        while j < len(cells) and cells[j].strip() and _HEADER_CELL_RE.match(cells[j].strip()):
            j += 1
        header = [c.strip() for c in cells[i:j]]
        start_col = _find_col(header, _H_START, _H_START_EN)
        time_col = _find_col(header, _H_TIME, _H_TIME_EN)
        text_col = _find_col(header, _H_TEXT, _H_TEXT_EN)
        known = sum(1 for h in header if _is_known_header(h))
        if len(header) >= 3 and known >= 2 and text_col is not None and (start_col is not None or time_col is not None):
            width = len(header)
            rows = [cells[k : k + width] for k in range(j, len(cells), width)]
            rows = [[c.replace("　", " ").strip() for c in r] for r in rows if len(r) == width]
            col = start_col if start_col is not None else time_col
            timed = sum(1 for r in rows if _time_cell(r[col], lenient=False)[0] is not None)
            if rows and timed >= max(2, 0.6 * len(rows)):
                return [header, *rows]
        i = max(j, i + 1)
    return None


def parse_tables(raw: str) -> list[dict] | None:
    """시각이 든 표가 있으면 그 행들을 큐로. 시각 있는 행이 2개 미만이면 None."""
    cues: list[dict] = []
    for rows in _table_rows(raw):
        cues.extend(_cues_from_rows(rows))
    if sum(1 for c in cues if c["start"] is not None) < 2:
        flat = _flattened_rows(raw)
        cues = _cues_from_rows(flat) if flat else []
    if sum(1 for c in cues if c["start"] is not None) < 2:
        return None
    _fill_open_ends(cues)
    return cues


def _cues_from_rows(rows: list[list[str]]) -> list[dict]:
    """표 한 덩어리(첫 행이 헤더일 수 있음) → 큐. 시각 있는 행이 2개 미만이면 표가 아니라고 본다."""
    header = rows[0]
    has_header = not any(_time_cell(c, lenient=False)[0] is not None for c in header)
    body = rows[1:] if has_header else rows
    cols: dict[str, int | None] = dict.fromkeys(("text", "reading", "time", "start", "end", "title", "number"))
    if has_header:
        # 시작·끝 열을 먼저 잡고, 그 열은 '시간' 열 후보에서 뺀다 — '시작시간'·'종료시간' 표
        cols["start"] = _find_col(header, _H_START, _H_START_EN)
        cols["end"] = _find_col(header, _H_END, _H_END_EN)
        taken = {c for c in (cols["start"], cols["end"]) if c is not None}
        cols["time"] = _find_col(header, _H_TIME, _H_TIME_EN, exclude=taken)
        taken |= {cols["time"]} if cols["time"] is not None else set()
        cols["reading"] = _find_col(header, _H_READING, (), exclude=taken)
        taken |= {cols["reading"]} if cols["reading"] is not None else set()
        cols["text"] = _find_col(header, _H_TEXT, _H_TEXT_EN, exclude=taken)
        taken |= {cols["text"]} if cols["text"] is not None else set()
        cols["title"] = _find_col(header, _H_TITLE, _H_TITLE_EN, exclude=taken)
        cols["number"] = _find_col(header, _H_NUMBER, _H_NUMBER_EN, exclude=taken)

    block: list[dict] = []
    for row in body:

        def cell(key: str) -> str:
            i = cols[key]
            return row[i] if i is not None and i < len(row) else ""

        start = end = None
        if cols["start"] is not None:
            start, end = _time_cell(cell("start"), lenient=True)
            if cols["end"] is not None:
                end = _time_cell(cell("end"), lenient=True)[0]
                start, end = _range(start, end) if start is not None else (start, end)
        if start is None and cols["time"] is not None:
            start, end = _time_cell(cell("time"), lenient=True)
        time_cols = {cols[k] for k in ("time", "start", "end") if cols[k] is not None}
        if start is None and not time_cols:
            for i, c in enumerate(row):
                start, end = _time_cell(c, lenient=False)
                if start is not None:
                    time_cols = {i}
                    break

        if cols["text"] is not None:
            text = _strip_inline(cell("text"))
        else:
            candidates = [
                _strip_inline(c) for i, c in enumerate(row) if i not in time_cols and re.search(r"[가-힣]", c)
            ]
            text = max(candidates, key=len, default="")
        text = strip_narration_label(text)
        if not text:
            continue  # 합계 줄 · 빈 줄

        title = _strip_inline(cell("title")) or None
        if title and (re.fullmatch(r"[\d.]+", title) or _time_cell(title, lenient=False)[0] is not None):
            title = None  # '구간' 열이 문장 순번이거나 시각인 표
        number_text = _strip_inline(cell("number"))
        block.append(
            {
                "start": start,
                "end": end,
                "title": title,
                "number": int(number_text) if number_text.isdigit() else None,
                "text": text,
                "reading": format_pairs(parse_reading_pairs(cell("reading"))),
            }
        )

    # 시간 열이 헤더로 확인된 표는 한 행짜리도 받는다(구간마다 표가 나뉜 대본). 헤더 없는 표는 2행 이상.
    known_time_col = cols["time"] is not None or cols["start"] is not None
    needed = 1 if known_time_col else 2
    return block if sum(1 for c in block if c["start"] is not None) >= needed else []


# ── 줄 단위 큐 ──────────────────────────────────────────────────────────────


def _heading_event(body: str, number: int | None = None) -> dict:
    """제목 줄(마크다운 '##' · 씬 머리줄) → 시각·제목·무음 여부."""
    body = _strip_inline(body)
    start = end = None
    m = _HEAD_RANGE_RE.search(body)
    # 콜론이나 '초' 가 붙은 범위만 시각이다 — '(03–05 교체 구간만)' 같은 씬 번호 범위를 0:03~0:05 로 읽지 않게
    if m and (_is_real_time(m.group("s")) or _is_real_time(m.group("e"))):
        start, end = _range(seconds_of(m.group("s")), seconds_of(m.group("e")) if m.group("e") else None)
    else:
        m = _HEAD_START_RE.search(body)
        if m:
            start = seconds_of(m.group("s"))
    title = body
    if m and start is not None:
        title = (body[: m.start()] + " " + body[m.end() :]).strip()
    silent = bool(_NO_NARRATION_RE.search(title))
    title = _NOTE_TAIL_RE.sub("", title).strip(" —–-·:") or None
    return {"kind": "heading", "start": start, "end": end, "title": title, "silent": silent, "number": number}


def _classify(line: str) -> dict:
    """줄 하나 → heading | section | cue | duration | plain | blank | rule"""
    stripped = line.strip().replace("　", " ").strip()
    if not stripped:
        return {"kind": "blank"}
    if _RULE_RE.match(stripped):
        return {"kind": "rule"}

    heading = _HEADING_RE.match(stripped)
    if heading:
        return _heading_event(heading.group("body"))

    body = _PREFIX_RE.sub("", stripped)
    plain_body = body.replace("**", "").strip()

    header = _SCENE_HEADER_RE.match(plain_body)
    if header and not _SENTENCE_END_RE.search(header.group("title")):
        zero_padded = len(header.group("num")) >= 2 and header.group("num").startswith("0")
        # 'S26 울트라가 …' 같은 본문을 머리줄로 오인하지 않게 한 글자 'S' 는 'S02' 처럼 0 을 채운 번호만 받는다
        named = header.group("kind") not in (None, "S")
        if zero_padded or named or header.group("pre") or header.group("time"):
            # 씬 머리줄은 마크다운 제목처럼 다룬다 — 아래 줄이 본문이거나, 아래 큐들의 제목이 된다
            title_part = header.group("title") + (" " + header.group("time") if header.group("time") else "")
            event = _heading_event(title_part, number=int(header.group("num")))
            return event

    titled = _TITLE_RANGE_RE.match(plain_body)
    if titled and not _SENTENCE_END_RE.search(titled.group("title")):
        start, end = _range(seconds_of(titled.group("s")), seconds_of(titled.group("e")) if titled.group("e") else None)
        title = _strip_inline(titled.group("title")) or None
        text = _strip_inline(titled.group("text") or "")
        if text:
            return {"kind": "cue", "start": start, "end": end, "title": title, "text": text, "raw": plain_body}
        return {"kind": "heading", "start": start, "end": end, "title": title, "silent": False, "number": None}

    m = _LEAD_RANGE_RE.match(body)
    if m and (m.group("e") or m.group("open")):
        s_tok, e_tok = m.group("s"), m.group("e")
        bracketed = bool(m.group("open") and m.group("close"))
        if _is_real_time(s_tok) or _is_real_time(e_tok) or (bracketed and e_tok):
            # '(0–6초)' 처럼 단위가 한쪽에만 붙은 범위는 양쪽 다 초다
            start, end = _range(seconds_of(s_tok), seconds_of(e_tok) if e_tok else None)
            return _cue_or_section(start, end, body[m.end() :], plain_body)

    m = _LEAD_START_RE.match(body)
    if m:
        token = m.group("b") or m.group("p") or m.group("s")
        return _cue_or_section(seconds_of(token), None, body[m.end() :], plain_body)

    m = _DURATION_ONLY_RE.match(body)
    if m:
        return {"kind": "duration", "value": seconds_of(m.group("d"))}

    m = _TITLE_DASH_RE.match(body)
    if m:
        return {
            "kind": "cue",
            "start": seconds_of(m.group("s")),
            "end": None,
            "title": _strip_inline(m.group("title")) or None,
            "text": _strip_inline(m.group("rest")).lstrip("—–-·: "),
            "raw": plain_body,
        }

    return {"kind": "plain", "text": _strip_inline(body)}


def _cue_or_section(start: float, end: float | None, rest: str, raw: str) -> dict:
    rest = _strip_inline(rest.lstrip("*_ "))
    if rest.startswith(("·", "|")):
        # '0:05 – 0:13 · 플랫폼 구도' — 본문이 아니라 구간 제목이다
        return {"kind": "section", "start": start, "end": end, "title": rest.lstrip("·| ").strip() or None}
    if _NO_NARRATION_RE.match(rest.lstrip("([ —–-")):
        # '(01:19–01:22.5 나레이션 없음 — 화면 유지)' — 이 구간은 비워 둔다
        return {"kind": "cue", "start": start, "end": end, "title": None, "text": "", "silent": True, "raw": raw}
    return {"kind": "cue", "start": start, "end": end, "title": None, "text": rest.lstrip("—–-: "), "raw": raw}


def looks_like_cue_script(raw: str) -> bool:
    """줄머리 시각 줄이 2개 이상이거나, 시각이 든 제목·머리줄이 있으면 큐 형식이다."""
    lead = 0
    for line in raw.split("\n"):
        event = _classify(line)
        if event["kind"] == "heading" and event["start"] is not None:
            return True
        if event["kind"] in ("cue", "section"):
            lead += 1
    return lead >= 2


def parse_cue_lines(raw: str) -> list[dict] | None:
    events = [_classify(line) for line in raw.split("\n")]

    # 시각 있는 제목이 있으면 그 앞은 머리말이다 — '45초–1:45 구간이 어렵다는 피드백…' 같은 줄을 큐로 오인하지 않는다
    first_timed_heading = next(
        (i for i, e in enumerate(events) if e["kind"] == "heading" and e["start"] is not None), None
    )
    if first_timed_heading is not None:
        events = events[first_timed_heading:]

    cues: list[dict] = []
    current: dict | None = None
    pending_title: str | None = None
    pending_number: int | None = None
    after_rule = False  # '---' 뒤 새 큐가 나오기 전의 줄은 꼬리말이다

    def close() -> None:
        nonlocal current, pending_title, pending_number
        if current is None:
            return
        if current.get("from_heading"):
            if current["lines"]:
                pending_title, pending_number = None, None  # 제목을 이 큐가 썼다
            else:
                # 본문 없는 제목 구간('## 2구간 (6–20초)' 아래에 큐들) — 시각만 남겨 앞 큐의 끝 계산에 쓰고
                # 제목은 다음 큐로 넘긴다
                current["silent"] = True
        cues.append(current)
        current = None

    for event in events:
        kind = event["kind"]
        if kind == "heading":
            close()
            after_rule = False
            pending_title, pending_number = event["title"], event.get("number")
            if event["start"] is not None:
                current = {**event, "lines": [], "from_heading": True}
        elif kind == "section":
            close()
            after_rule = False
            pending_title, pending_number = event["title"], None
        elif kind == "cue":
            close()
            after_rule = False
            title = event["title"] or pending_title
            number = pending_number if not event["title"] else None
            pending_title, pending_number = None, None
            current = {
                **event,
                "title": title,
                "number": number,
                # 'Outro [0:49–0:56] — …' 처럼 줄에 제목을 단 큐 — 일부러 적은 큐라 '튀는 시각'으로 합치지 않는다
                "own_title": bool(event["title"]),
                "lines": [event["text"]] if event["text"] else [],
                # 시각 줄에 본문이 붙어 있던 큐 — 빈 줄 뒤에 오는 줄은 그 큐의 본문이 아니다(꼬리말)
                "inline": bool(event["text"]),
            }
        elif kind == "duration":
            # '0:00' 다음 줄의 '7초' — 시작 뒤 길이
            if current is not None and not current["lines"] and current.get("end") is None:
                current["end"] = current["start"] + event["value"]
        elif kind == "blank":
            if current is not None and current.get("inline"):
                current["sealed"] = True
        elif kind == "rule":
            close()
            after_rule = True
        elif current is not None and not current.get("sealed") and not after_rule:
            current["lines"].append(event["text"])
    close()

    _merge_out_of_order(cues)
    has_timed_heading = any(c.get("from_heading") and c["start"] is not None for c in cues)
    if sum(1 for c in cues if c["start"] is not None) < (1 if has_timed_heading else 2):
        return None
    _fill_open_ends(cues)

    result: list[dict] = []
    for cue in cues:
        text = _narration_text(cue["lines"])
        if cue.get("silent") or not text:
            continue
        number, title = cue.get("number"), cue.get("title")
        if title and number is None:
            m = _HEAD_NUMBER_RE.match(title)
            if m:
                number, title = int(m.group("num")), m.group("title").strip()
        result.append(
            {"start": cue["start"], "end": cue["end"], "title": title, "number": number, "text": text, "reading": None}
        )
    return result or None


def _merge_out_of_order(cues: list[dict]) -> None:
    """앞뒤 큐보다 시각이 혼자 튀는 줄은 시각이 아니라 본문이다 — '10:30, 회의가 시작됩니다.'

    줄머리 시각 큐(제목 줄 제외) 중, 빼고 나면 앞뒤가 다시 이어지는(다음 시작 ≥ 이전 시작) 것만
    앞 큐의 본문으로 되돌린다. 대본 두 편을 이어 붙여 시각이 0 으로 다시 시작하는 곳은 건드리지 않는다.
    """
    i = 1
    while i < len(cues) - 1:
        cue, prev, nxt = cues[i], cues[i - 1], cues[i + 1]
        if (
            not cue.get("from_heading")
            and not cue.get("own_title")
            and cue.get("raw")
            and cue["start"] is not None
            and nxt.get("start") is not None
            and prev.get("start") is not None
            and cue["start"] > nxt["start"] >= prev["start"]
        ):
            prev["lines"].extend([cue["raw"], *cue["lines"][1:]])
            del cues[i]
            continue
        i += 1


def _narration_text(lines: list[str]) -> str:
    # 낭독 표시('V/O', 'NA' 한 줄)가 있으면 그 뒤만 본문이다 (앞은 화면 설명). 번호만 있는 줄에서 끊긴다(다음 장면 머리).
    vo = [i for i, line in enumerate(lines) if _VO_RE.match(line.strip())]
    if vo:
        lines = lines[vo[-1] + 1 :]
    kept: list[str] = []
    for line in lines:
        line = line.strip()
        if _NUMBER_ONLY_RE.match(line):
            if vo:
                break
            continue
        if not line or is_note_line(line):
            continue
        line = strip_narration_label(line)
        if line:
            kept.append(_INLINE_NUM_RE.sub("", line))
    return " ".join(" ".join(kept).split())


def _fill_open_ends(cues: list[dict]) -> None:
    """끝 시각이 없거나 다음 큐 시작을 넘는 큐는 다음 큐의 시작에서 끊는다 (마지막 큐는 열린 채로).

    바로 다음 시각만 본다 — 대본 두 편을 이어 붙여 시각이 다시 0 으로 돌아가면 그 뒤 큐로 끊지 않는다.
    """
    for i, cue in enumerate(cues):
        if cue.get("start") is None:
            continue
        later = next((c for c in cues[i + 1 :] if c.get("start") is not None), None)
        if later is not None and later["start"] > cue["start"]:
            if cue.get("end") is None or cue["end"] > later["start"]:
                cue["end"] = later["start"]
