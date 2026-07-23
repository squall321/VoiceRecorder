# 내레이션 스크립트 원문을 씬(번호·제목·타임코드·본문) 리스트로 파싱한다

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 사용자 스크립트는 en dash(–, U+2013) 를 쓴다. 하이픈만 처리하면 전부 파싱에 실패하므로
# 하이픈·en dash·em dash·물결 을 모두 구분자로 받는다.
_DASH = r"[-–—−~]"

# 0:08 / 01:02:03 / 1:06.5 / 12:34,500 모두 허용
_TC = r"\d{1,3}:\d{1,2}(?::\d{1,2})?(?:[.,]\d{1,3})?"

_TIMECODE_RE = re.compile(
    rf"[(\[]\s*(?P<start>{_TC})\s*{_DASH}\s*(?P<end>{_TC})\s*[)\]]"
)

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


def _normalize_block(block: str) -> str:
    """블록 안의 줄바꿈을 공백으로 접는다 — 한 씬은 이어서 읽는 한 덩어리다."""
    return " ".join(line.strip() for line in block.splitlines() if line.strip())


def _parse_block(block: str, index: int) -> ParsedScene | None:
    raw = _normalize_block(block)
    if not raw:
        return None

    number: int | None = None
    m = _NUMBER_RE.match(raw)
    if m:
        number = int(m.group("num"))
        rest = raw[m.end() :]
    else:
        rest = raw

    # 본문이 따옴표로 열리면 그 앞까지만 헤더로 본다.
    # (본문 안에 괄호가 있어도 타임코드로 오인하지 않게 하는 장치)
    quote_match = _QUOTE_OPEN_RE.search(rest)
    if quote_match:
        header, body = rest[: quote_match.start()], rest[quote_match.start() :]
    else:
        header, body = rest, ""

    start_sec = end_sec = duration_hint = None
    tc = _TIMECODE_RE.search(header)
    if tc:
        try:
            start_sec = parse_timecode(tc.group("start"))
            end_sec = parse_timecode(tc.group("end"))
        except ValueError:
            start_sec = end_sec = None
        header = (header[: tc.start()] + " " + header[tc.end() :]).strip()
    else:
        # 타임코드가 없으면 '(8초)' 형식을 본다. 타임코드가 우선이다.
        dur = _DURATION_PAREN_RE.search(header)
        if dur:
            try:
                duration_hint = float(dur.group("value").replace(",", "."))
            except ValueError:
                duration_hint = None
            header = (header[: dur.start()] + " " + header[dur.end() :]).strip()

    if not body:
        # 따옴표가 없는 형식. 타임코드가 있으면 그 앞이 제목, 뒤가 본문이다.
        if tc:
            header = rest[: tc.start()].strip()
            body = rest[tc.end() :].strip()
        else:
            body, header = header, ""

    title = header.strip(" .:–-") or None
    text = _strip_quotes(body)
    if not text:
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

    1순위: 빈 줄로 구분된 블록. 각 블록에서 `01 제목 (0:00–0:08) "본문"` 을 벗겨낸다.
    폴백:  빈 줄이 하나도 없으면 번호로 시작하는 줄마다 새 씬으로 끊고,
           그것도 없으면 줄 단위로 끊는다.
    """
    raw = (raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return ParseResult()

    blocks = [b for b in _BLOCK_SPLIT_RE.split(raw) if b.strip()]
    if len(blocks) == 1:
        blocks = _split_single_block(raw)

    scenes: list[ParsedScene] = []
    for block in blocks:
        scene = _parse_block(block, len(scenes))
        if scene is not None:
            scenes.append(scene)

    _fill_cumulative_targets(scenes)
    structured = any(s.number is not None or s.target_start_sec is not None for s in scenes)
    return ParseResult(scenes=scenes, structured=structured)


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
