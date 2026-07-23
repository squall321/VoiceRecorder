# 씬별 실제 합성 길이와 무음 간격으로 전체 타임라인을 계산하고 SRT 자막을 만든다

from __future__ import annotations

from dataclasses import dataclass

from .script_parser import format_timecode


@dataclass
class TimelineEntry:
    scene_id: str
    index: int
    number: int | None
    title: str | None
    text: str
    gap_before_sec: float
    speech_start_sec: float
    speech_end_sec: float
    gap_after_sec: float
    target_duration_sec: float | None

    @property
    def speech_duration_sec(self) -> float:
        return self.speech_end_sec - self.speech_start_sec

    @property
    def drift_sec(self) -> float | None:
        """목표 길이 대비 실제 길이 차이. 양수면 초과(잘라야 함), 음수면 부족."""
        if self.target_duration_sec is None:
            return None
        return self.speech_duration_sec - self.target_duration_sec


@dataclass
class Timeline:
    entries: list[TimelineEntry]
    total_sec: float

    @property
    def ready_count(self) -> int:
        return len(self.entries)


def build_timeline(scenes: list[dict]) -> Timeline:
    """오디오가 준비된 씬들로 타임라인을 만든다.

    scenes 의 각 항목은 `duration_sec`(속도 반영 후 실제 길이)를 가져야 한다.
    준비되지 않은 씬(duration_sec 없음)은 타임라인에서 제외된다 — 아직 길이를 모르므로
    뒤 씬의 시각을 계산할 수 없기 때문이다.
    """
    entries: list[TimelineEntry] = []
    cursor = 0.0

    for scene in scenes:
        duration = scene.get("duration_sec")
        if not duration:
            continue
        gap_before = max(0.0, (scene.get("gap_before_ms") or 0) / 1000.0)
        gap_after = max(0.0, (scene.get("gap_after_ms") or 0) / 1000.0)

        start = cursor + gap_before
        end = start + float(duration)
        entries.append(
            TimelineEntry(
                scene_id=scene["id"],
                index=scene["position"],
                number=scene.get("number"),
                title=scene.get("title"),
                text=scene.get("text", ""),
                gap_before_sec=gap_before,
                speech_start_sec=start,
                speech_end_sec=end,
                gap_after_sec=gap_after,
                target_duration_sec=scene.get("target_duration_sec"),
            )
        )
        cursor = end + gap_after

    return Timeline(entries=entries, total_sec=cursor)


def render_srt(timeline: Timeline, *, max_line_chars: int = 42) -> str:
    """타임라인 → SRT 자막. 한 줄이 길면 두 줄로 접는다."""
    blocks: list[str] = []
    for ordinal, entry in enumerate(timeline.entries, start=1):
        start = format_timecode(entry.speech_start_sec, millis=True)
        end = format_timecode(entry.speech_end_sec, millis=True)
        body = _wrap(entry.text, max_line_chars)
        blocks.append(f"{ordinal}\n{start} --> {end}\n{body}")
    # SRT 는 블록 사이 빈 줄, 파일 끝 개행을 요구한다
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _wrap(text: str, max_chars: int) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= max_chars:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    # 자막은 2줄까지가 읽기 편하다. 넘치면 나머지를 마지막 줄에 몰아넣는다.
    if len(lines) > 2:
        lines = [lines[0], " ".join(lines[1:])]
    return "\n".join(lines)
