# 표·줄머리 타임코드·마크다운 제목 구간 형식의 대본에서 큐(시작·끝·제목·본문·읽는 법)를 뽑는다

"""기존 블록 파서(`01 제목 (0:00–0:08) "본문"`)가 못 읽는 형식을 맡는다.

실제로 받아 본 대본 형식들:
  - 줄머리 타임코드      `0:00–0:07 본문` · `0:05 본문` · `**(0.3–6.0)** 본문` · `- [6.1초] 본문`
  - 구간 머리줄 + 큐     `0:05 – 0:13 · 플랫폼 구도` 다음 줄부터 `0:05 본문`
  - 제목 — 시각          `Platform — 0:00` 다음 줄들이 본문, `Stakes — 0:21 4. 문장 5. 문장`
  - 마크다운 제목 구간   `## 01 오프닝 (0:00–0:18.8)` 아래 문장들 / `## 1구간 (0–6초)` 아래 큐들
  - 표                   마크다운 `| 번호 | 시간 | 대본 |`, 엑셀에서 복사한 탭 구분 표(시작·끝 열)
  - 읽는 법              표의 「읽는 법」 열, `읽는 법: A = 가, B = 나` 줄

결과는 dict 리스트다. ParsedScene 변환과 따옴표 정리는 script_parser 가 한다(순환 임포트 방지).
"""

from __future__ import annotations

import re

from .textnorm import parse_reading_pairs

_DASH = r"[-–—−~]"
_COLON_TC = r"\d{1,3}:\d{1,2}(?::\d{1,2})?(?:[.,]\d{1,3})?"
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
# 'Platform — 0:00' / 'Stakes — 0:21 4. 문장'
_TITLE_DASH_RE = re.compile(rf"^(?P<title>[^\s\d\[(#|][^\n]{{0,40}}?)\s+[—–-]\s+(?P<s>{_COLON_TC})(?![\d:])(?P<rest>.*)$")
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<body>.+)$")
# 제목 안의 시각 — 괄호 범위('(0:00–0:18.8)' '(0–6초)' '(22.5초~)') 또는 괄호 속 콜론 시각 하나
_HEAD_RANGE_RE = re.compile(rf"[\[(]\s*(?P<s>{_ANY})\s*{_DASH}\s*(?P<e>{_ANY})?\s*[\])]")
_HEAD_START_RE = re.compile(rf"[\[(]\s*(?P<s>{_COLON_TC})\s*[\])]")

_RULE_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,}|={3,})$")
_DIRECTION_RE = re.compile(r"^[(\[].*[)\]]$")  # (타이틀 화면) 같은 화면 지시
_LABEL_RE = re.compile(r"^[가-힣A-Za-z][가-힣A-Za-z ./]{0,11}\s*[:：]")  # '화면:' '바뀐 점:' 메모
_VO_RE = re.compile(r"^(?:V/?O|나레이션|내레이션)$", re.IGNORECASE)
_NUMBER_ONLY_RE = re.compile(r"^\d{1,3}$")
_DURATION_ONLY_RE = re.compile(rf"^(?P<d>{_SEC_TC})$")
_INLINE_NUM_RE = re.compile(r"(?:^|(?<=[.!?。…]\s))\d{1,3}\.\s+")
_NO_NARRATION_RE = re.compile(r"(?:나레이션|내레이션|자막)\s*없음|무음")
_HEAD_NUMBER_RE = re.compile(r"^(?P<num>\d{1,3})[.)]?\s+(?P<title>\S.*)$")
_NOTE_TAIL_RE = re.compile(r"\s+[—–]\s+.*$")

_READING_LINE_RE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:\*\*)?\s*(?:읽는\s?법|읽기)\s*(?:\*\*)?\s*[:：]\s*(?P<pairs>.+)$"
)


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
    text = text.replace("**", "").replace("__", "").replace("　", " ")
    return " ".join(text.split())


# ── 읽는 법 줄 ──────────────────────────────────────────────────────────────


def extract_reading_lines(raw: str) -> tuple[str, list[tuple[str, str]]]:
    """대본 머리의 `읽는 법: HWAX = 하드웨어 에이엑스, UW = 유더블유` 줄을 떼어 쌍으로 돌려준다."""
    pairs: list[tuple[str, str]] = []
    kept: list[str] = []
    for line in raw.split("\n"):
        m = _READING_LINE_RE.match(line)
        if m:
            pairs.extend(parse_reading_pairs(m.group("pairs")))
        else:
            kept.append(line)
    return "\n".join(kept), pairs


def format_pairs(pairs: list[tuple[str, str]]) -> str | None:
    seen: dict[str, str] = {}
    for source, target in pairs:
        seen.setdefault(source, target)
    return " · ".join(f"{s} → {t}" for s, t in seen.items()) or None


# ── 표 (마크다운 · 탭 구분) ─────────────────────────────────────────────────

_H_TEXT = ("나레이션", "내레이션", "대본", "원고", "멘트", "스크립트", "자막")
_H_TEXT_EN = ("narration", "script", "text", "voiceover")
_H_READING = ("읽는", "읽기")
_H_TIME = ("시간", "타임코드", "타임")
_H_TIME_EN = ("time", "tc", "timecode")
_H_START = ("시작",)
_H_START_EN = ("start", "in")
_H_END = ("끝", "종료")
_H_END_EN = ("end", "out")
_H_TITLE = ("장면", "씬", "제목", "구간", "섹션")
_H_TITLE_EN = ("scene", "title", "section")
_H_NUMBER = ("번호",)
_H_NUMBER_EN = ("no", "#", "no.")


def _find_col(header: list[str], korean: tuple[str, ...], english: tuple[str, ...]) -> int | None:
    lowered = [h.lower() for h in header]
    for keyword in korean:
        for i, h in enumerate(lowered):
            if keyword in h:
                return i
    for keyword in english:
        for i, h in enumerate(lowered):
            if re.fullmatch(rf"\W*{re.escape(keyword)}\W*", h):
                return i
    return None


def _time_cell(cell: str, *, lenient: bool) -> tuple[float | None, float | None]:
    """셀 하나에서 (시작, 끝). lenient=True(시간 열로 확인됨)면 맨 숫자도 초로 받는다."""
    cell = _strip_inline(cell)
    if not cell:
        return None, None
    m = re.fullmatch(rf"(?P<s>{_ANY})\s*{_DASH}\s*(?P<e>{_ANY})?", cell)
    if m and (lenient or _is_real_time(m.group("s")) or _is_real_time(m.group("e"))):
        end = seconds_of(m.group("e")) if m.group("e") else None
        return seconds_of(m.group("s")), end
    single = _ANY if lenient else _TIME
    if re.fullmatch(single, cell):
        return seconds_of(cell), None
    return None, None


def _table_rows(raw: str) -> list[list[list[str]]]:
    """연속된 표 줄을 블록으로 묶는다. 빈 줄은 블록을 끊지 않는다(붙여넣기가 줄을 띄우곤 한다)."""
    blocks: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("|") and stripped.count("|") >= 2:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
        elif "\t" in line:
            cells = [c.strip() for c in line.split("\t")]
        else:
            if current:
                blocks.append(current)
                current = []
            continue
        if all(re.fullmatch(r":?-{2,}:?", c) or not c for c in cells):
            continue  # 마크다운 구분 줄
        current.append(cells)
    if current:
        blocks.append(current)
    return blocks


_HEADER_CELL_RE = re.compile(r"^[^\d:]{1,24}$")


def _flattened_rows(raw: str) -> list[list[str]] | None:
    """엑셀 표를 붙여넣을 때 칸마다 줄이 바뀐 형태 — 헤더 칸 N개 뒤로 N칸씩 행이 이어진다.

    빈 칸은 전각 공백(　) 한 줄로 온다. 그 줄을 지우면 칸이 밀리므로 ASCII 공백만 빈 줄로 본다.
    헤더는 숫자·시각이 없는 짧은 칸이 3개 이상 이어지고 그중에 본문 열과 시각 열이 있어야 한다.
    """
    cells = [line.strip(" \t") for line in raw.split("\n") if line.strip(" \t")]
    i = 0
    while i < len(cells):
        j = i
        while j < len(cells) and cells[j].strip() and _HEADER_CELL_RE.match(cells[j].strip()):
            j += 1
        header = [c.strip() for c in cells[i:j]]
        has_time = (
            _find_col(header, _H_START, _H_START_EN) is not None
            or _find_col(header, _H_TIME, _H_TIME_EN) is not None
        )
        if len(header) >= 3 and has_time and _find_col(header, _H_TEXT, _H_TEXT_EN) is not None:
            width = len(header)
            rows = [cells[k : k + width] for k in range(j, len(cells), width)]
            rows = [[c.replace("　", " ").strip() for c in r] for r in rows if len(r) == width]
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
    cols = {
        "text": _find_col(header, _H_TEXT, _H_TEXT_EN) if has_header else None,
        "reading": _find_col(header, _H_READING, ()) if has_header else None,
        "time": _find_col(header, _H_TIME, _H_TIME_EN) if has_header else None,
        "start": _find_col(header, _H_START, _H_START_EN) if has_header else None,
        "end": _find_col(header, _H_END, _H_END_EN) if has_header else None,
        "title": _find_col(header, _H_TITLE, _H_TITLE_EN) if has_header else None,
        "number": _find_col(header, _H_NUMBER, _H_NUMBER_EN) if has_header else None,
    }

    block: list[dict] = []
    for row in body:

        def cell(key: str) -> str:
            i = cols[key]
            return row[i] if i is not None and i < len(row) else ""

        start = end = None
        if cols["time"] is not None:
            start, end = _time_cell(cell("time"), lenient=True)
        if start is None and cols["start"] is not None:
            start, _ = _time_cell(cell("start"), lenient=True)
            if cols["end"] is not None:
                end, _ = _time_cell(cell("end"), lenient=True)
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
        if not text:
            continue  # 합계 줄 · 빈 줄

        title = _strip_inline(cell("title")) or None
        if title and re.fullmatch(r"[\d.]+", title):
            title = None  # '구간' 열이 문장 순번인 표
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


def _classify(line: str) -> dict:
    """줄 하나 → heading | section | cue | duration | plain | skip"""
    stripped = line.strip().replace("　", " ").strip()
    if not stripped or _RULE_RE.match(stripped):
        return {"kind": "skip"}

    heading = _HEADING_RE.match(stripped)
    if heading:
        body = _strip_inline(heading.group("body"))
        start = end = None
        m = _HEAD_RANGE_RE.search(body)
        if m and (_is_real_time(m.group("s")) or _is_real_time(m.group("e")) or m.group("e")):
            start = seconds_of(m.group("s"))
            end = seconds_of(m.group("e")) if m.group("e") else None
        else:
            m = _HEAD_START_RE.search(body)
            if m:
                start = seconds_of(m.group("s"))
        title = body
        if m and start is not None:
            title = (body[: m.start()] + " " + body[m.end() :]).strip()
        silent = bool(_NO_NARRATION_RE.search(title))
        title = _NOTE_TAIL_RE.sub("", title).strip(" —–-·:") or None
        return {"kind": "heading", "start": start, "end": end, "title": title, "silent": silent}

    body = _PREFIX_RE.sub("", stripped)

    m = _LEAD_RANGE_RE.match(body)
    if m and (m.group("e") or m.group("open")):
        s_tok, e_tok = m.group("s"), m.group("e")
        bracketed = bool(m.group("open") and m.group("close"))
        if _is_real_time(s_tok) or _is_real_time(e_tok) or (bracketed and e_tok):
            # '(0–6초)' 처럼 단위가 한쪽에만 붙은 범위는 양쪽 다 초다
            start = seconds_of(s_tok)
            end = seconds_of(e_tok) if e_tok else None
            return _cue_or_section(start, end, body[m.end() :])

    m = _LEAD_START_RE.match(body)
    if m:
        token = m.group("b") or m.group("p") or m.group("s")
        return _cue_or_section(seconds_of(token), None, body[m.end() :])

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
        }

    return {"kind": "plain", "text": _strip_inline(body)}


def _cue_or_section(start: float, end: float | None, rest: str) -> dict:
    rest = _strip_inline(rest.lstrip("*_ "))
    if rest.startswith(("·", "|")):
        # '0:05 – 0:13 · 플랫폼 구도' — 본문이 아니라 구간 제목이다
        return {"kind": "section", "start": start, "end": end, "title": rest.lstrip("·| ").strip() or None}
    if _NO_NARRATION_RE.search(rest):
        # '(01:19–01:22.5 나레이션 없음 — 화면 유지)' — 이 구간은 비워 둔다
        return {"kind": "cue", "start": start, "end": end, "title": None, "text": "", "silent": True}
    return {"kind": "cue", "start": start, "end": end, "title": None, "text": rest.lstrip("—–-: ")}


def looks_like_cue_script(raw: str) -> bool:
    """줄머리 시각 줄이 2개 이상이거나, 시각이 든 마크다운 제목이 있으면 큐 형식이다."""
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
    events = [e for e in events if e["kind"] != "skip"]

    # 시각 있는 제목이 있으면 그 앞은 머리말이다 — '45초–1:45 구간이 어렵다는 피드백…' 같은 줄을 큐로 오인하지 않는다
    first_timed_heading = next(
        (i for i, e in enumerate(events) if e["kind"] == "heading" and e["start"] is not None), None
    )
    if first_timed_heading is not None:
        events = events[first_timed_heading:]

    cues: list[dict] = []
    current: dict | None = None
    pending_title: str | None = None

    def close() -> None:
        nonlocal current, pending_title
        if current is None:
            return
        if current.get("from_heading"):
            if current["lines"]:
                pending_title = None  # 제목을 이 큐가 썼다
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
            pending_title = event["title"]
            if event["start"] is not None:
                current = {**event, "lines": [], "from_heading": True}
        elif kind == "section":
            close()
            pending_title = event["title"]
        elif kind == "cue":
            close()
            title = event["title"] or pending_title
            pending_title = None
            current = {**event, "title": title, "lines": [event["text"]] if event["text"] else []}
        elif kind == "duration":
            # '0:00' 다음 줄의 '7초' — 시작 뒤 길이
            if current is not None and not current["lines"] and current.get("end") is None:
                current["end"] = current["start"] + event["value"]
        elif current is not None:
            current["lines"].append(event["text"])
    close()

    if sum(1 for c in cues if c["start"] is not None) < 2:
        return None
    _fill_open_ends(cues)

    result: list[dict] = []
    for cue in cues:
        text = _narration_text(cue["lines"])
        if cue.get("silent") or not text:
            continue
        number, title = None, cue.get("title")
        if title:
            m = _HEAD_NUMBER_RE.match(title)
            if m:
                number, title = int(m.group("num")), m.group("title").strip()
        result.append(
            {"start": cue["start"], "end": cue["end"], "title": title, "number": number, "text": text, "reading": None}
        )
    return result or None


def _narration_text(lines: list[str]) -> str:
    # 'V/O' 표시가 있으면 그 뒤만 본문이다 (앞은 화면 설명). 번호만 있는 줄에서 끊긴다(다음 장면 머리).
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
        if not line or _DIRECTION_RE.match(line) or _LABEL_RE.match(line) or line.startswith("※"):
            continue
        kept.append(_INLINE_NUM_RE.sub("", line))
    return " ".join(" ".join(kept).split())


def _fill_open_ends(cues: list[dict]) -> None:
    """끝 시각이 없거나 다음 큐 시작을 넘는 큐는 다음 큐의 시작에서 끊는다 (마지막 큐는 열린 채로)."""
    for i, cue in enumerate(cues):
        if cue.get("start") is None:
            continue
        for later in cues[i + 1 :]:
            if later.get("start") is not None and later["start"] > cue["start"]:
                if cue.get("end") is None or cue["end"] > later["start"]:
                    cue["end"] = later["start"]
                break
