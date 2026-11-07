"""timeline_strip: pure marks, labels and click mapping for one strip."""

from datetime import date, datetime

T0 = datetime(2026, 11, 6, 10, 0, 0).timestamp()
TODAY = date(2026, 11, 6)


def _item(
    state,
    t0: float | None = T0,
    t1=None,
    name="exp",
    uuid: str | None = "u1",
    qidx=None,
):
    return {
        "uuid": uuid,
        "name": name,
        "state": state,
        "t_start": t0,
        "t_end": t1,
        "qidx": qidx,
    }


def test_done_label():
    from helao.ui.reflex.timeline_strip import segment_label

    assert segment_label(_item("done", t1=T0 + 65), T0 + 100, False, TODAY) == (
        "exp",
        "10:00:00–10:01:05",
    )


def test_active_label_carries_elapsed():
    from helao.ui.reflex.timeline_strip import segment_label

    assert segment_label(_item("active"), T0 + 125, False, TODAY) == (
        "exp",
        "10:00:00– (2:05)",
    )
    assert (
        segment_label(_item("active"), T0 + 3725, False, TODAY)[1]
        == "10:00:00– (1:02:05)"
    )


def test_queued_label_has_no_time():
    from helao.ui.reflex.timeline_strip import segment_label

    assert segment_label(_item("queued", t0=None), T0, False, TODAY) == ("exp", "")


def test_narrow_label_is_start_time_only():
    from helao.ui.reflex.timeline_strip import segment_label

    assert segment_label(_item("done", t1=T0 + 5), T0 + 9, True, TODAY) == (
        "",
        "10:00:00",
    )


def test_cross_day_prefix():
    from helao.ui.reflex.timeline_strip import segment_label

    line2 = segment_label(_item("done", t1=T0 + 65), T0, False, date(2026, 11, 7))[1]
    assert line2 == "11-06 10:00:00–11-06 10:01:05"


def test_window_ellipses_and_click_mapping():
    from helao.ui.reflex.timeline_strip import click_item, strip_marks

    items = [
        _item("done", uuid="a", t1=T0 + 1),
        _item("active", uuid="b"),
        _item("queued", t0=None, uuid=None, qidx=0),
    ]
    marks, slots = strip_marks(
        items, n_before=20, n_after=3, now=T0 + 5, width_px=720, today=TODAY
    )
    assert slots[0] is None and slots[-1] is None and len(slots) == 5
    values = [m["value"] for m in marks if m["kind"] == "text"]
    assert "+20" in values and "+3" in values
    hit = click_item(slots, 2.4)
    assert hit is not None and hit["uuid"] == "b"
    assert click_item(slots, 0.5) is None  # ellipsis
    assert click_item(slots, 9.0) is None and click_item(slots, -0.1) is None


def test_selected_segment_is_outlined_and_unknown_state_is_queued_colour():
    from helao.ui.reflex.timeline_strip import strip_marks
    from helao.ui.shared.palette import GROUP_SELECTED_OUTLINE, GROUP_STATE_COLORS

    items = [_item("done", uuid="a", t1=T0 + 1), _item("weird", uuid="b")]
    marks, _ = strip_marks(
        items, n_before=0, n_after=0, now=T0, width_px=720, selected="b", today=TODAY
    )
    outlines = [
        m["x"]
        for m in marks
        if m["kind"] == "vline" and m["color"] == GROUP_SELECTED_OUTLINE
    ]
    assert outlines == [1, 2]
    bands = [m["color"] for m in marks if m["kind"] == "band"]
    assert bands == [GROUP_STATE_COLORS["done"], GROUP_STATE_COLORS["queued"]]


def test_strip_always_has_the_progress_and_hit_traces():
    from helao.ui.reflex.timeline_strip import strip_marks

    marks, _ = strip_marks([], n_before=0, n_after=0, now=T0, width_px=720, today=TODAY)
    assert [m["name"] for m in marks if m["kind"] in ("line", "scatter")] == [
        "progress",
        "hit",
    ]
    marks, _ = strip_marks(
        [_item("active")],
        n_before=0,
        n_after=0,
        now=T0 + 0.25,
        width_px=720,
        today=TODAY,
    )
    progress = next(m for m in marks if m.get("name") == "progress")
    assert progress["x"][0] == 0 and 0.0 <= progress["x"][1] - progress["x"][0] < 1.0


def test_item_key_prefers_uuid_then_queue_index():
    from helao.ui.reflex.timeline_strip import item_key

    assert item_key({"uuid": "x", "qidx": None}) == "x"
    assert item_key({"uuid": None, "qidx": 4}) == "q4"


def test_progress_bar_sits_below_every_text_annotation():
    from helao.ui.reflex.timeline_strip import strip_marks

    items = [_item("active"), _item("queued", t0=None, uuid="q", qidx=0)]
    marks, _ = strip_marks(
        items, n_before=2, n_after=0, now=T0 + 0.25, width_px=720, today=TODAY
    )
    progress = next(m for m in marks if m.get("name") == "progress")
    assert progress["y"], "active segment must draw progress"
    text_ys = [m["y"] for m in marks if m["kind"] == "text"]
    assert text_ys and max(progress["y"]) < min(text_ys)


def test_narrow_strip_drops_names_and_progress_follows_the_sawtooth():
    from helao.ui.reflex.timeline_strip import strip_marks

    items = [_item("active", uuid=str(i)) for i in range(9)]
    marks, _ = strip_marks(
        items, n_before=0, n_after=0, now=T0, width_px=720, today=TODAY
    )
    assert "exp" not in [m["value"] for m in marks if m["kind"] == "text"]
    marks, _ = strip_marks(
        items[:1], n_before=0, n_after=0, now=T0, width_px=720, today=TODAY
    )
    assert "exp" in [m["value"] for m in marks if m["kind"] == "text"]
    p = lambda now: next(
        m
        for m in strip_marks(
            items[:1], n_before=0, n_after=0, now=now, width_px=720, today=TODAY
        )[0]
        if m.get("name") == "progress"
    )["x"][1]
    assert abs(p(T0 + 0.125) - 0.25) < 1e-6 and abs(p(T0 + 0.5) - p(T0)) < 1e-6


def test_only_an_active_row_counts_elapsed_time():
    from helao.ui.reflex.timeline_strip import fmt_hms, segment_label

    t0 = T0
    for state in ("done", "error"):  # no end recorded: never a running counter
        _, line2 = segment_label(_item(state, t1=None), T0 + 500, False, TODAY)
        assert line2 == f"{fmt_hms(t0, TODAY)}–" and "(" not in line2
    _, active = segment_label(_item("active"), T0 + 125, False, TODAY)
    assert active.endswith("(2:05)")
    # a queued row shows no time even when a stale t_start is set
    assert segment_label(_item("queued", t0=T0), T0, False, TODAY) == ("exp", "")
    assert segment_label(_item("queued", t0=T0), T0, True, TODAY) == ("", "")
