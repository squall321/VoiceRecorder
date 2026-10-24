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


# ── 음성 씌우기 배치 (타임코드 고정) ────────────────────────────────────────


def timed(sid, position, duration, start, end=None, **kw):
    return {**scene(sid, position, duration, **kw), "target_start_sec": start, "target_end_sec": end}


def test_place_on_timecode_anchors_each_scene_at_its_start():
    from app.timeline import place_on_timecode

    timeline, overruns = place_on_timecode(
        [timed("a", 0, 3.0, 0.5, 4.0), timed("b", 1, 2.0, 6.0, 9.0), timed("c", 2, 1.0, 9.0)]
    )
    assert [e.speech_start_sec for e in timeline.entries] == [0.5, 6.0, 9.0]
    assert timeline.total_sec == 10.0
    assert overruns == []


def test_place_on_timecode_pushes_colliding_scene_after_a_breath():
    from app.timeline import MIN_BREATH_SEC, place_on_timecode

    timeline, overruns = place_on_timecode([timed("a", 0, 5.0, 0.0, 4.0), timed("b", 1, 2.0, 4.0, 6.0)])
    b = timeline.entries[1]
    assert b.speech_start_sec == 5.0 + MIN_BREATH_SEC
    # a 는 목표 끝을 1초 넘기고, b 는 1.2초 밀려 목표 끝도 넘긴다
    assert [(o["scene_id"], o["pushed_sec"], o["over_sec"]) for o in overruns] == [
        ("a", 0.0, 1.0),
        ("b", 1.2, 1.2),
    ]


def test_place_on_timecode_untimed_scenes_follow_continuous_rules():
    from app.timeline import place_on_timecode

    timeline, _ = place_on_timecode(
        [timed("a", 0, 2.0, 1.0), scene("b", 1, 1.0, before=100, after=0), timed("c", 2, 1.0, 10.0)]
    )
    # b 는 a 끝(3.0) + a 의 뒤 무음(0.4) + b 의 앞 무음(0.1)
    assert [round(e.speech_start_sec, 3) for e in timeline.entries] == [1.0, 3.5, 10.0]
