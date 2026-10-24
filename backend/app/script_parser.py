# 내레이션 스크립트 원문을 씬(번호·제목·타임코드·본문) 리스트로 파싱한다

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .script_formats import (
    extract_reading_lines,
    format_pairs,
    is_note_line,
    looks_like_cue_script,
    parse_cue_lines,
    parse_subtitles,
    parse_tables,
    strip_narration_label,
)
from .textnorm import contains_term, parse_reading_pairs

# 사용자 스크립트는 en dash(–, U+2013) 를 쓴다. 하이픈만 처리하면 전부 파싱에 실패하므로
# 하이픈·en dash·em dash·물결 을 모두 구분자로 받는다.
_DASH = r"[-–—−~]"

# 0:08 / 01:02:03 / 1:06.5 / 12:34,500 모두 허용
_TC = r"\d{1,3}:\d{1,2}(?::\d{1,2})?(?:[.,]\d{1,3})?"
_SECS = r"\d{1,4}(?:[.,]\d+)?"

# 괄호 시각 — '(0:00–0:08)' '(0:00–0:08 / 8초)' '(0:00–0:08 8초)' '(0:00–0:08초)' '(0:00)' '(0–8초)'.
# 맨 숫자는 '초' 가 붙은 범위일 때만 시각이다 — '(8초)' 는 길이, '(1–3)' 은 시각이 아니다.
_TIMECODE_RE = re.compile(
    rf"[(\[]\s*(?P<start>{_TC}|{_SECS})\s*(?:{_DASH}\s*(?P<end>{_TC}|{_SECS})?)?\s*(?P<sec>초)?"
    rf"\s*(?:[/·,|\s][^)\]]*)?[)\]]"
)
# 괄호 없는 범위 '01 오프닝 0:00–0:08 본문' — 번호 붙은 머리에서만 본다
_BARE_RANGE_RE = re.compile(rf"(?<![\d:])(?P<start>{_TC})\s*{_DASH}\s*(?P<end>{_TC})(?![\d:])")
# '01 Platform — 0:00 본문'
_DASH_START_RE = re.compile(rf"\s[—–-]\s*(?P<start>{_TC})(?![\d:])")
# 본문 뒤에 붙은 시각 — '01 오프닝 "본문" (0:00–0:08)'
_TRAILING_TC_RE = re.compile(rf"[(\[]\s*(?P<start>{_TC})\s*(?:{_DASH}\s*(?P<end>{_TC}))?\s*[)\]]\s*$")
# 따옴표로 감싼 짧은 제목 — "01 '오프닝' (0:00–0:08) …"
_QUOTED_TITLE_RE = re.compile(r"^(?P<q>['\"“‘「『])(?P<title>[^'\"”’」』]{1,20})['\"”’」』]\s*(?=[(\[])")
# 머리로 볼 수 있는 앞부분 — 짧고 문장 끝 부호가 없어야 한다('평균 대기 시간은 (약 3초) 수준' 은 본문)
_HEADER_MAX = 30

# 전각 구두점 → 반각 (전각 공백 U+3000 은 엑셀 빈 칸 표시라 건드리지 않는다 — NFKC 를 쓰지 않는 이유)
_FULLWIDTH = str.maketrans(
    {"～": "~", "〜": "~", "：": ":", "（": "(", "）": ")", "【": "[", "】": "]", "［": "[", "］": "]",
     "－": "-", "｜": "|", "，": ",", "―": "—"}
)  # fmt: skip
_EDGE_WS = " \t\r\n"  # 끝을 다듬을 때 전각 공백(마지막 빈 칸)은 남긴다

# "01 " / "1) " / "[02] " / "씬 3." / "Scene 4 -" 등 선두 번호
_NUMBER_RE = re.compile(
    r"^\s*\[?\s*(?:씬|장면|Scene|SCENE|scene|S)?\s*(?P<num>\d{1,3})\s*\]?\s*[.):\-–]?\s+"
)

# 끝 시각 대신 지속시간만 적은 형식 — '(8초)' '(8초, ~32자)' '(약 8초)' '(8s)'.
# 뒤에 붙는 글자수 메모 같은 건 통째로 삼킨다.
_DURATION_PAREN_RE = re.compile(
    r"[(\[]\s*(?:약\s*)?(?P<value>\d{1,4}(?:[.,]\d+)?)\s*(?:초|sec(?:onds?|s)?|s)\b[^)\]]*[)\]]",
    re.IGNORECASE,
)

_QUOTE_CHARS = "\"'“”‘’「」『』«»"
_QUOTE_OPEN_RE = re.compile(f"[{re.escape(_QUOTE_CHARS)}]")

# 'Hook [0:00–0:07] — 본문' 처럼 타임코드와 본문 사이에 낀 구분 기호
_LEADING_SEP_RE = re.compile(r"^\s*(?:[—–:|·]|-(?=\s))\s*")

_BLOCK_SPLIT_RE = re.compile(r"\n\s*\n+")

# 문장 종결 기준 — 긴 씬을 합성 단위로 쪼갤 때 쓴다
_SENTENCE_END_RE = re.compile(r"(?<=[.!?。！？…])\s+|(?<=[다요](?:\.|!|\?))\s+")


@dataclass
class ParsedScene:
    """파싱된 씬 하나. index 는 0-based 순서, number 는 스크립트에 적힌 번호."""

    index: int
    text: str
    number: int | None = None
    title: str | None = None
    target_start_sec: float | None = None
    target_end_sec: float | None = None
    # '(8초)' 처럼 길이만 적힌 경우. 시작 시각은 앞 씬들을 누적해 parse_script 가 채운다.
    duration_hint_sec: float | None = None
    # 읽는 법 — 'AI → 에이아이 · 6만 → 육만'. 자막(text)은 그대로 두고 합성 소리만 바꾼다.
    reading: str | None = None

    @property
    def target_duration_sec(self) -> float | None:
        if self.target_start_sec is None or self.target_end_sec is None:
            return None
        d = self.target_end_sec - self.target_start_sec
        return d if d > 0 else None


@dataclass
class ParseResult:
    scenes: list[ParsedScene] = field(default_factory=list)
    # 헤더(번호/타임코드)를 실제로 인식했는지 — UI 가 "구조 인식됨" 배지를 띄우는 데 쓴다
    structured: bool = False


def parse_timecode(value: str) -> float:
    """'0:08' → 8.0, '1:06' → 66.0, '01:02:03' → 3723.0, '0:08.5' → 8.5"""
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if not 2 <= len(parts) <= 3:
        raise ValueError(f"잘못된 타임코드: {value!r}")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def format_timecode(seconds: float, *, millis: bool = False) -> str:
    """SRT/UI 표시용. millis=True 면 SRT 형식(HH:MM:SS,mmm)."""
    seconds = max(0.0, seconds)
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    if millis:
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _strip_quotes(text: str) -> str:
    """본문을 감싼 따옴표만 벗긴다.

    양끝을 각각 탐욕적으로 벗기면 안 된다 — `"'인용'이라던 말."` 처럼 본문이 인용으로
    시작하면 여는 작은따옴표까지 먹어서 짝 없는 따옴표가 남는다.
    양끝이 **둘 다** 따옴표일 때만 한 쌍씩 벗긴다.
    """
    text = text.strip()
    while len(text) >= 2 and text[0] in _QUOTE_CHARS and text[-1] in _QUOTE_CHARS:
        text = text[1:-1].strip()
    return text


def _normalize_block(block: str) -> tuple[str, bool]:
    """블록 안의 줄바꿈을 공백으로 접는다 — 한 씬은 이어서 읽는 한 덩어리다.

    마크다운 제목·강조 기호를 벗기고, 화면 지시·메모 줄('화면: 로고', '(타이틀 화면)')은 뺀다.
    두 번째 값은 '마크다운 제목 한 줄뿐인 블록'인지 — 문서·구간 제목이라 읽지 않는다.
    """
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    heading_only = len(lines) == 1 and lines[0].startswith("#")
    kept: list[str] = []
    for i, line in enumerate(lines):
        line = re.sub(r"^#{1,6}\s+", "", line).replace("**", "").strip()
        if i > 0 and is_note_line(line):
            continue
        line = strip_narration_label(line) if i > 0 else line
        if line:
            kept.append(line)
    return " ".join(kept), heading_only


def _header_time(header: str, *, numbered: bool) -> tuple[float | None, float | None, tuple[int, int] | None]:
    """머리 부분에서 (시작, 끝, 찾은 자리). 번호 없는 머리는 괄호 속 콜론 시각만 본다."""
    for m in _TIMECODE_RE.finditer(header):
        start_tok, end_tok = m.group("start"), m.group("end")
        if ":" in start_tok:
            start = parse_timecode(start_tok)
            end = parse_timecode(end_tok) if end_tok and ":" in end_tok else None
        elif end_tok and m.group("sec"):  # '(0–8초)'
            start, end = float(start_tok.replace(",", ".")), float(end_tok.replace(",", "."))
        else:
            continue
        return start, (end if end is None or end > start else None), m.span()
    if numbered:
        m = _BARE_RANGE_RE.search(header) or _DASH_START_RE.search(header)
        if m:
            start = parse_timecode(m.group("start"))
            end_tok = m.groupdict().get("end")
            end = parse_timecode(end_tok) if end_tok else None
            return start, (end if end is None or end > start else None), m.span()
    return None, None, None


def _is_header_prefix(text: str) -> bool:
    return len(text) <= _HEADER_MAX and not re.search(r"[.!?。…]", text)


def _parse_block(block: str, index: int) -> ParsedScene | None:
    raw, heading_only = _normalize_block(block)
    if not raw or heading_only:
        return None

    number: int | None = None
    m = _NUMBER_RE.match(raw)
    if m:
        number = int(m.group("num"))
        rest = raw[m.end() :]
    else:
        rest = raw

    quoted_title = None
    qt = _QUOTED_TITLE_RE.match(rest)
    if qt:
        quoted_title, rest = qt.group("title").strip(), rest[qt.end() :]

    # 본문이 따옴표로 열리면 그 앞까지만 헤더로 본다.
    # (본문 안에 괄호가 있어도 타임코드로 오인하지 않게 하는 장치)
    quote_match = _QUOTE_OPEN_RE.search(rest)
    if quote_match:
        header, body = rest[: quote_match.start()], rest[quote_match.start() :]
    else:
        header, body = rest, ""

    start_sec = end_sec = duration_hint = None
    found = False
    if quote_match or number is not None:
        start_sec, end_sec, span = _header_time(header, numbered=number is not None)
    else:
        # 번호도 따옴표도 없는 문단 — 'Hook [0:00–0:07] — 본문' 처럼 짧은 제목 뒤 괄호 시각만 머리로 본다
        start_sec, end_sec, span = _header_time(header, numbered=False)
        if span and not _is_header_prefix(header[: span[0]]):
            start_sec = end_sec = span = None
    if span:
        found = True
        if quote_match:
            header = (header[: span[0]] + " " + header[span[1] :]).strip()
        else:
            # 따옴표가 없는 형식 — 시각 앞이 제목, 뒤가 본문이다
            if not _is_header_prefix(header[: span[0]]):
                start_sec = end_sec = None
                found = False
            else:
                header, body = rest[: span[0]].strip(), rest[span[1] :].strip()
    if not found and (quote_match or number is not None):
        # 타임코드가 없으면 '(8초)' 형식을 본다(머리 자리에 있을 때만). 타임코드가 우선이다.
        dur = _DURATION_PAREN_RE.search(header)
        if dur and _is_header_prefix(header[: dur.start()]):
            try:
                duration_hint = float(dur.group("value").replace(",", "."))
            except ValueError:
                duration_hint = None
            if quote_match:
                header = (header[: dur.start()] + " " + header[dur.end() :]).strip()
            else:
                # '01 오프닝 (8초) 본문' — 길이 앞이 제목, 뒤가 본문
                header, body = header[: dur.start()].strip(), header[dur.end() :].strip()

    if quote_match and not found:
        # 시각이 본문 뒤에 붙은 경우 — '01 오프닝 "본문" (0:00–0:08)'
        tail = _TRAILING_TC_RE.search(body)
        if tail:
            start_sec = parse_timecode(tail.group("start"))
            end_sec = parse_timecode(tail.group("end")) if tail.group("end") else None
            body = body[: tail.start()].strip()
            found = True

    if not body and not found and duration_hint is None:
        body, header = header, ""

    title = quoted_title or header.strip(" .:–-") or None
    text = _strip_quotes(_LEADING_SEP_RE.sub("", body))
    if not text:
        if found or duration_hint is not None:
            return None  # 시각만 있고 본문이 없는 머리 — 구간·문서 제목이라 읽지 않는다
        # 헤더만 있고 본문이 비었으면 제목을 본문으로 승격 (버려지는 텍스트가 없게)
        if not title:
            return None
        text, title = title, None

    return ParsedScene(
        index=index,
        text=text,
        number=number,
        title=title,
        target_start_sec=start_sec,
        target_end_sec=end_sec,
        duration_hint_sec=duration_hint,
    )


def parse_script(raw: str) -> ParseResult:
    """스크립트 원문 → 씬 리스트.

    0순위: 시각이 든 표(마크다운·탭 구분), 그다음 줄머리 시각·마크다운 제목 구간 형식
           (script_formats). 어느 쪽이든 `읽는 법:` 줄은 먼저 떼어 씬 읽는 법으로 붙인다.
    1순위: 빈 줄로 구분된 블록. 각 블록에서 `01 제목 (0:00–0:08) "본문"` 을 벗겨낸다.
    폴백:  빈 줄이 하나도 없으면 번호로 시작하는 줄마다 새 씬으로 끊고,
           그것도 없으면 줄 단위로 끊는다.
    """
    raw = (raw or "").replace("\r\n", "\n").replace("\r", "\n").translate(_FULLWIDTH).strip(_EDGE_WS)
    if not raw.strip():
        return ParseResult()

    raw, reading_pairs = extract_reading_lines(raw)
    result = _parse_cue_formats(raw) or _parse_blocks(raw.strip(_EDGE_WS))
    _attach_reading(result.scenes, reading_pairs)
    return result


def _parse_cue_formats(raw: str) -> ParseResult | None:
    cues = parse_subtitles(raw) or parse_tables(raw)
    if cues is None and looks_like_cue_script(raw):
        cues = parse_cue_lines(raw)
    if not cues:
        return None
    scenes: list[ParsedScene] = []
    for cue in cues:
        text = _strip_quotes(cue["text"])
        if not text:
            continue
        scenes.append(
            ParsedScene(
                index=len(scenes),
                text=text,
                number=cue["number"],
                title=cue["title"],
                target_start_sec=cue["start"],
                target_end_sec=cue["end"],
                reading=cue["reading"],
            )
        )
    return ParseResult(scenes=scenes, structured=True) if scenes else None


def _attach_reading(scenes: list[ParsedScene], script_pairs: list[tuple[str, str]]) -> None:
    """대본 머리의 읽는 법 중 그 씬 본문에 실제로 나오는 것만 씬 읽는 법에 더한다."""
    for scene in scenes:
        pairs = parse_reading_pairs(scene.reading)
        # 경계를 지켜 찾는다 — '6만 → 육만' 이 '16만' 씬에 붙지 않게(합성 치환과 같은 규칙)
        pairs += [(s, t) for s, t in script_pairs if contains_term(scene.text, s)]
        scene.reading = format_pairs(pairs)


def _parse_blocks(raw: str) -> ParseResult:
    if not raw:
        return ParseResult()

    blocks = [b for b in _BLOCK_SPLIT_RE.split(raw) if b.strip()]
    if len(blocks) == 1:
        blocks = _split_single_block(raw)
    else:
        # 빈 줄 하나로 문서 제목만 떼어 놓고 나머지는 한 줄에 한 씬인 대본 — 블록 안에서도 씬 줄마다 끊는다
        blocks = [chunk for block in blocks for chunk in _split_timed_lines(block)]

    scenes: list[ParsedScene] = []
    for block in blocks:
        scene = _parse_block(block, len(scenes))
        if scene is not None:
            scenes.append(scene)

    _fill_cumulative_targets(scenes)
    _fill_ends_from_next_start(scenes)
    scenes = _trim_untimed_edges(scenes)
    structured = any(s.number is not None or s.target_start_sec is not None for s in scenes)
    return ParseResult(scenes=scenes, structured=structured)


def _split_timed_lines(block: str) -> list[str]:
    """블록 안에 '번호 + 시각' 줄이 둘 이상이면 그 줄마다 새 씬으로 끊는다(하나면 그대로)."""
    lines = [ln for ln in block.splitlines() if ln.strip()]
    starts = [i for i, ln in enumerate(lines) if _NUMBER_RE.match(ln) and _line_has_time(ln)]
    if len(starts) < 2:
        return [block]
    chunks = ["\n".join(lines[s : (starts[k + 1] if k + 1 < len(starts) else len(lines))]) for k, s in enumerate(starts)]
    if starts[0] > 0:
        chunks.insert(0, "\n".join(lines[: starts[0]]))
    return chunks


def _line_has_time(line: str) -> bool:
    return bool(_TIMECODE_RE.search(line) or _BARE_RANGE_RE.search(line) or _DURATION_PAREN_RE.search(line))


def _fill_ends_from_next_start(scenes: list[ParsedScene]) -> None:
    """시작만 적힌 씬('01 오프닝 (0:00) …')은 다음 씬 시작에서 끝난다고 본다."""
    for scene, nxt in zip(scenes, scenes[1:]):
        if scene.target_start_sec is not None and scene.target_end_sec is None:
            if nxt.target_start_sec is not None and nxt.target_start_sec > scene.target_start_sec:
                scene.target_end_sec = nxt.target_start_sec


def _trim_untimed_edges(scenes: list[ParsedScene]) -> list[ParsedScene]:
    """타임코드가 있는 대본에서 맨 앞·맨 뒤의 시각도 번호도 없는 덩어리는 문서 제목·메모·꼬리말이다.

    예: 앞의 'HWAX 협업진단 플랫폼 — 소개영상 내레이션 대본 (2분 57초 · 14씬)', 뒤의 '위 대본을 1.2배로
    읽어 주세요.' 남겨 두면 영상의 0초나 끝에 읽힌다. 번호가 붙은 씬은 시각이 없어도 씬이라 남긴다.
    타임코드가 2개 미만인 대본은 손대지 않는다.
    """
    timed = [i for i, s in enumerate(scenes) if s.target_start_sec is not None]
    if len(timed) < 2:
        return scenes

    def droppable(scene: ParsedScene) -> bool:
        return scene.target_start_sec is None and scene.number is None

    first, last = 0, len(scenes)
    while first < timed[0] and droppable(scenes[first]):
        first += 1
    while last - 1 > timed[-1] and droppable(scenes[last - 1]):
        last -= 1
    kept = scenes[first:last]
    for index, scene in enumerate(kept):
        scene.index = index
    return kept


def _fill_cumulative_targets(scenes: list[ParsedScene]) -> None:
    """'(8초)' 처럼 길이만 적힌 씬에 시작·끝 시각을 앞에서부터 누적해 채운다.

    타임코드가 명시된 씬은 건드리지 않고, 그 끝 시각을 이후 누적의 기준으로 삼는다
    (두 형식이 섞여 있어도 어긋나지 않게).
    """
    cursor = 0.0
    for scene in scenes:
        if scene.target_start_sec is None and scene.duration_hint_sec:
            scene.target_start_sec = cursor
            scene.target_end_sec = cursor + scene.duration_hint_sec
        if scene.target_end_sec is not None:
            cursor = scene.target_end_sec


def _split_single_block(raw: str) -> list[str]:
    """빈 줄이 없는 스크립트 — 번호로 시작하는 줄, 없으면 줄 단위로 끊는다."""
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if len(lines) <= 1:
        return [raw]

    numbered = [i for i, ln in enumerate(lines) if _NUMBER_RE.match(ln)]
    if len(numbered) >= 2:
        chunks: list[str] = []
        for pos, start in enumerate(numbered):
            end = numbered[pos + 1] if pos + 1 < len(numbered) else len(lines)
            chunks.append("\n".join(lines[start:end]))
        if numbered[0] > 0:  # 번호 앞의 머리말도 살린다
            chunks.insert(0, "\n".join(lines[: numbered[0]]))
        return chunks
    if numbered:
        # 번호가 하나뿐이면 씬도 하나다 — 줄바꿈은 본문 안의 개행일 뿐이다
        return [raw]
    return lines


def chunk_text(text: str, max_chars: int = 300) -> list[str]:
    """긴 씬을 합성 단위로 쪼갠다.

    TTS 모델은 한 번에 처리할 수 있는 길이에 한계가 있어, 긴 문단을 통째로 넘기면
    뒷부분이 잘리거나 발음이 무너진다. 문장 경계에서 끊고, 한 문장이 그래도 길면
    쉼표/공백에서 강제로 끊는다.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentences = [s.strip() for s in _SENTENCE_END_RE.split(text) if s.strip()]
    chunks: list[str] = []
    buf = ""
    for sentence in sentences:
        for piece in _force_split(sentence, max_chars):
            if not buf:
                buf = piece
            elif len(buf) + 1 + len(piece) <= max_chars:
                buf = f"{buf} {piece}"
            else:
                chunks.append(buf)
                buf = piece
    if buf:
        chunks.append(buf)
    return chunks


def _force_split(sentence: str, max_chars: int) -> list[str]:
    """한 문장이 max_chars 를 넘으면 쉼표 → 공백 순으로 끊는다."""
    if len(sentence) <= max_chars:
        return [sentence]
    out: list[str] = []
    remaining = sentence
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        cut = max(window.rfind(","), window.rfind("、"), window.rfind(";"))
        if cut < max_chars // 3:
            cut = window.rfind(" ")
        if cut < max_chars // 3:
            cut = max_chars - 1
        out.append(remaining[: cut + 1].strip())
        remaining = remaining[cut + 1 :].strip()
    if remaining:
        out.append(remaining)
    return out
