# 타임라인 계산과 SRT 렌더링

from __future__ import annotations

from app.timeline import build_timeline, render_srt


def scene(sid, position, duration, *, before=0, after=400, target=None, text="본문"):
    return {
        "id": sid,
        "position": position,
        "duration_sec": duration,
        "gap_before_ms": before,
        "gap_after_ms": after,
        "target_duration_sec": target,
        "text": text,
        "number": position + 1,
        "title": None,
    }


def test_timeline_accumulates_gaps():
    timeline = build_timeline([scene("a", 0, 8.0), scene("b", 1, 11.0), scene("c", 2, 12.0)])

    assert [round(e.speech_start_sec, 3) for e in timeline.entries] == [0.0, 8.4, 19.8]
    assert [round(e.speech_end_sec, 3) for e in timeline.entries] == [8.0, 19.4, 31.8]
    assert round(timeline.total_sec, 3) == 32.2  # 마지막 씬의 gap_after 포함


def test_lead_in_gap_shifts_everything():
    timeline = build_timeline([scene("a", 0, 5.0, before=1000, after=0)])

    assert timeline.entries[0].speech_start_sec == 1.0
    assert timeline.entries[0].speech_end_sec == 6.0
    assert timeline.total_sec == 6.0


def test_scenes_without_audio_are_skipped():
    rows = [scene("a", 0, 8.0), scene("b", 1, None), scene("c", 2, 4.0)]
    timeline = build_timeline(rows)

    assert [e.scene_id for e in timeline.entries] == ["a", "c"]


def test_drift_against_target_duration():
    timeline = build_timeline([scene("a", 0, 7.6, target=8.0), scene("b", 1, 12.5, target=11.0)])

    assert round(timeline.entries[0].drift_sec, 3) == -0.4  # 목표보다 짧다
    assert round(timeline.entries[1].drift_sec, 3) == 1.5  # 목표보다 길다


def test_drift_is_none_without_target():
    timeline = build_timeline([scene("a", 0, 7.6)])
    assert timeline.entries[0].drift_sec is None


def test_empty_timeline():
    timeline = build_timeline([])
    assert timeline.entries == []
    assert timeline.total_sec == 0.0


def test_srt_structure_matches_timeline():
    timeline = build_timeline(
        [scene("a", 0, 8.0, text="첫 씬입니다."), scene("b", 1, 11.0, text="둘째 씬입니다.")]
    )
    srt = render_srt(timeline)

    assert srt.startswith("1\n00:00:00,000 --> 00:00:08,000\n첫 씬입니다.")
    assert "2\n00:00:08,400 --> 00:00:19,400\n둘째 씬입니다." in srt
    assert srt.endswith("\n")
    # 블록 사이는 빈 줄 하나
    assert "첫 씬입니다.\n\n2\n" in srt


def test_srt_wraps_long_lines_to_two():
    long_text = " ".join(["단어"] * 60)
    srt = render_srt(build_timeline([scene("a", 0, 8.0, text=long_text)]))
    body = srt.split("\n", 2)[2].strip()

    assert len(body.splitlines()) == 2


def test_empty_srt_is_empty_string():
    assert render_srt(build_timeline([])) == ""
