"""timeline_strip: pure marks, labels and click mapping for one strip."""

from datetime import date, datetime

import pytest

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
        "10:00:00",
        "10:01:05",
    )
    # error is a finished state like done; no end recorded gives a dash
    assert segment_label(_item("error", t1=None), T0 + 9, False, TODAY) == (
        "exp",
        "10:00:00",
        "—",
    )


def test_active_label_carries_elapsed():
    from helao.ui.reflex.timeline_strip import segment_label

    assert segment_label(_item("active"), T0 + 125, False, TODAY) == (
        "exp",
        "10:00:00",
        "(2:05)",
    )
    assert segment_label(_item("active"), T0 + 3725, False, TODAY)[2] == "(1:02:05)"


def test_queued_label_has_no_time():
    from helao.ui.reflex.timeline_strip import segment_label

    assert segment_label(_item("queued", t0=None), T0, False, TODAY) == (
        "exp",
        "",
        "",
    )


def test_narrow_label_is_start_time_only():
    from helao.ui.reflex.timeline_strip import segment_label

    assert segment_label(_item("done", t1=T0 + 5), T0 + 9, True, TODAY) == (
        "exp",
        "10:00:00",
        "",
    )
    # narrow active: start only too, no elapsed
    assert segment_label(_item("active"), T0 + 9, True, TODAY) == (
        "exp",
        "10:00:00",
        "",
    )


def test_cross_day_prefix():
    from helao.ui.reflex.timeline_strip import segment_label

    lines = segment_label(_item("done", t1=T0 + 65), T0, False, date(2026, 11, 7))
    assert lines[1:] == ("11-06 10:00:00", "11-06 10:01:05")
    # the prefix is per time: an end on the day shown carries none
    lines = segment_label(
        _item("done", t0=T0 - 86400, t1=T0), T0, False, date(2026, 11, 6)
    )
    assert lines[1:] == ("11-05 10:00:00", "10:00:00")


def test_window_ellipses_and_click_mapping():
    from helao.ui.reflex.timeline_strip import click_item, strip_marks

    items = [
        _item("done", uuid="a", t1=T0 + 1),
        _item("active", uuid="b"),
        _item("queued", t0=None, uuid=None, qidx=0),
    ]
    marks, slots, edges = strip_marks(
        items, n_before=20, n_after=3, now=T0 + 5, width_px=720, today=TODAY
    )
    assert slots[0] is None and slots[-1] is None and len(slots) == 5
    values = [m["value"] for m in marks if m["kind"] == "text"]
    assert "+20" in values and "+3" in values
    sw = 720 / 5
    hit = click_item(slots, edges, 2.4 * sw)
    assert hit is not None and hit["uuid"] == "b"
    assert click_item(slots, edges, 0.5 * sw) is None  # ellipsis
    assert click_item(slots, edges, 9.0 * sw) is None
    assert click_item(slots, edges, -0.1) is None


def test_selected_segment_is_outlined_and_unknown_state_is_queued_colour():
    from helao.ui.reflex.timeline_strip import strip_marks
    from helao.ui.shared.palette import GROUP_SELECTED_OUTLINE, GROUP_STATE_COLORS

    items = [_item("done", uuid="a", t1=T0 + 1), _item("weird", uuid="b")]
    marks, *_ = strip_marks(
        items, n_before=0, n_after=0, now=T0, width_px=720, selected="b", today=TODAY
    )
    outlines = [
        m["x"]
        for m in marks
        if m["kind"] == "vline" and m["color"] == GROUP_SELECTED_OUTLINE
    ]
    assert outlines == [360.0, 720.0]
    bands = [m["color"] for m in marks if m["kind"] == "band"]
    assert bands == [GROUP_STATE_COLORS["done"], GROUP_STATE_COLORS["queued"]]


def test_strip_has_only_the_hit_trace_and_no_progress_trace():
    from helao.ui.reflex.timeline_strip import strip_marks

    for items in ([], [_item("active")]):
        marks, *_ = strip_marks(
            items, n_before=0, n_after=0, now=T0 + 0.25, width_px=720, today=TODAY
        )
        # the bar is drawn in the browser; annotation bands paint over any trace
        assert [m["name"] for m in marks if m["kind"] in ("line", "scatter")] == ["hit"]
        assert not [m for m in marks if m.get("name") == "progress"]


def test_item_key_prefers_uuid_then_queue_index():
    from helao.ui.reflex.timeline_strip import item_key

    assert item_key({"uuid": "x", "qidx": None}) == "x"
    assert item_key({"uuid": None, "qidx": 4}) == "q4"


def test_narrow_strip_keeps_every_name():
    from helao.ui.reflex.timeline_strip import strip_marks

    # 8 queued at 704 px is 88 px a segment: narrow, yet every name stays
    items = [_item("queued", uuid=str(i), t0=None) for i in range(8)]
    marks, *_ = strip_marks(
        items, n_before=0, n_after=0, now=T0, width_px=704, today=TODAY
    )
    assert [m["value"] for m in marks if m["kind"] == "text"] == ["exp"] * 8


def test_only_an_active_row_counts_elapsed_time():
    from helao.ui.reflex.timeline_strip import fmt_hms, segment_label

    t0 = T0
    for state in ("done", "error"):  # no end recorded: never a running counter
        _, line2, line3 = segment_label(_item(state, t1=None), T0 + 500, False, TODAY)
        assert (line2, line3) == (fmt_hms(t0, TODAY), "—")
    _, _, active = segment_label(_item("active"), T0 + 125, False, TODAY)
    assert active == "(2:05)"
    # a queued row shows no time even when a stale t_start is set
    assert segment_label(_item("queued", t0=T0), T0, False, TODAY) == (
        "exp",
        "",
        "",
    )
    assert segment_label(_item("queued", t0=T0), T0, True, TODAY) == ("exp", "", "")


def _texts(marks):
    return [m for m in marks if m["kind"] == "text"]


def test_every_label_is_boxed_inside_its_segment():
    from helao.ui.reflex.timeline_strip import LABEL_PAD_PX, strip_marks

    items = [
        _item("done", uuid=str(i), t1=T0 + 1, name="a_long_name") for i in range(7)
    ]
    marks, *_ = strip_marks(
        items, n_before=3, n_after=0, now=T0, width_px=960, today=TODAY
    )
    texts = _texts(marks)
    assert len(texts) == 3 * 7 + 1  # name, start and end of every item, plus the +3
    assert {t["max_px"] for t in texts} == {960 / 8 - 2 * LABEL_PAD_PX}


def test_a_segment_too_small_for_even_a_truncated_label_has_none():
    from helao.ui.reflex.timeline_strip import strip_marks

    items = [_item("done", uuid=str(i), t1=T0 + 1) for i in range(40)]
    marks, *_ = strip_marks(
        items, n_before=0, n_after=1, now=T0, width_px=704, today=TODAY
    )
    # 41 slots squeeze to 10.6 px slivers (the ellipsis alone is wider); only the
    # two key slots (last finished and its previous) keep labels: 3 lines each
    assert len(_texts(marks)) == 6
    marks, *_ = strip_marks(
        items[:20], n_before=0, n_after=0, now=T0, width_px=704, today=TODAY
    )
    assert _texts(marks)  # 35 px: narrow mode keeps the start time


# ---- minimum-width key slots ---------------------------------------------------

W = 704.0


def _states(*names):
    return [
        _item(n, uuid=str(i), t0=None if n == "queued" else T0, t1=T0 + 1)
        for i, n in enumerate(names)
    ]


def _widths(edges):
    return [b - a for a, b in zip(edges, edges[1:])]


def test_equal_widths_while_every_slot_fits_the_minimum():
    from helao.ui.reflex.timeline_strip import MIN_KEY_PX, strip_marks

    n = int(W // MIN_KEY_PX)  # 11: 64 px each
    items = _states(*["done"] * 5, "active", *["queued"] * 5)
    assert len(items) == n
    marks, slots, edges = strip_marks(
        items, n_before=0, n_after=0, now=T0, width_px=W, today=TODAY
    )
    assert edges == tuple(i * W / n for i in range(n)) + (W,)
    bands = [m for m in marks if m["kind"] == "band"]
    assert [(b["x0"], b["x1"]) for b in bands] == list(zip(edges, edges[1:]))
    assert [m["x"] for m in marks if m["kind"] == "vline"] == list(edges[1:-1])


def test_squeezed_key_slots_keep_the_minimum_and_the_rest_share_the_remainder():
    from helao.ui.reflex.timeline_strip import MIN_KEY_PX, key_indices, strip_marks

    items = _states(*["done"] * 10, "active", *["queued"] * 10)
    _, slots, edges = strip_marks(
        items, n_before=0, n_after=0, now=T0, width_px=W, today=TODAY
    )
    keys = key_indices(slots)
    assert keys == {9, 10, 11}
    w = _widths(edges)
    assert all(w[i] == pytest.approx(MIN_KEY_PX) for i in keys)
    rest = [x for i, x in enumerate(w) if i not in keys]
    assert rest == pytest.approx([(W - 3 * MIN_KEY_PX) / 18] * 18)
    assert edges[0] == 0.0 and edges[-1] == W and abs(sum(w) - W) < 1e-9


def test_ellipsis_slots_are_squeezed_with_the_rest_and_never_key():
    from helao.ui.reflex.timeline_strip import MIN_KEY_PX, key_indices, strip_marks

    items = _states(*["done"] * 5, "active", *["queued"] * 5)
    _, slots, edges = strip_marks(
        items, n_before=20, n_after=9, now=T0, width_px=W, today=TODAY
    )
    assert slots[0] is None and slots[-1] is None
    keys = key_indices(slots)
    assert keys == {5, 6, 7}  # shifted by the leading +20
    w = _widths(edges)
    assert w[0] == pytest.approx(w[-1]) == pytest.approx(w[1])
    assert w[0] != pytest.approx(MIN_KEY_PX)


def _keys(*names):
    from helao.ui.reflex.timeline_strip import key_indices

    return key_indices(_states(*names))


def test_key_roles():
    assert _keys("done", "done", "active", "queued", "queued") == {1, 2, 3}  # middle
    assert _keys("active", "queued", "queued") == {0, 1}  # no previous
    assert _keys("done", "done", "active") == {1, 2}  # no next
    # idle: the last finished item takes the active role; its next is the head queued
    assert _keys("done", "done", "done") == {1, 2}
    assert _keys("done", "done", "queued", "queued") == {0, 1, 2}
    assert _keys("queued", "queued") == {0}  # nothing finished: head of the queue
    assert _keys() == set()


def test_fallback_to_equal_widths_when_the_keys_alone_overflow():
    from helao.ui.reflex.timeline_strip import MIN_KEY_PX, strip_marks

    w = 2.5 * MIN_KEY_PX  # three keys need 360 > 300
    items = _states("done", "active", "queued", "queued", "queued", "queued")
    _, _, edges = strip_marks(
        items, n_before=0, n_after=0, now=T0, width_px=w, today=TODAY
    )
    assert edges == tuple(i * w / 6 for i in range(6)) + (w,)


def test_click_and_hit_map_across_uneven_widths_including_both_ends():
    from helao.ui.reflex.timeline_strip import (
        HIT_COLS,
        HIT_ROWS,
        click_item,
        hit_slot,
        strip_marks,
    )

    items = _states(*["done"] * 10, "active", *["queued"] * 10)
    items[0]["name"], items[-1]["name"] = "first", "last"
    _, slots, edges = strip_marks(
        items, n_before=0, n_after=0, now=T0, width_px=W, today=TODAY
    )
    for i, it in enumerate(slots):
        for x in (edges[i] + 0.01, (edges[i] + edges[i + 1]) / 2, edges[i + 1] - 0.01):
            assert click_item(slots, edges, x) is it, (i, x)
    assert click_item(slots, edges, 0.0)["name"] == "first"
    assert click_item(slots, edges, W - 0.01)["name"] == "last"
    assert click_item(slots, edges, W) is None and click_item(slots, edges, -1) is None
    assert click_item(slots, edges, float("nan")) is None
    for idx in range(HIT_COLS * HIT_ROWS):
        col = idx % HIT_COLS
        xc = (col + 0.5) * W / HIT_COLS
        s = hit_slot(idx, edges)
        assert edges[s] <= xc < edges[s + 1]
    assert hit_slot(-1, edges) is None and hit_slot(HIT_COLS * HIT_ROWS, edges) is None


def test_every_slot_a_column_wide_is_reachable_through_the_hit_grid():
    from helao.ui.reflex.timeline_strip import HIT_COLS, HIT_ROWS, hit_slot, strip_marks

    for n_q in (3, 12, 30, 50):
        items = _states(*["done"] * 20, "active", *["queued"] * n_q)
        _, slots, edges = strip_marks(
            items, n_before=0, n_after=0, now=T0, width_px=W, today=TODAY
        )
        reach = {hit_slot(i, edges) for i in range(HIT_COLS * HIT_ROWS)}
        wide = {i for i, w in enumerate(_widths(edges)) if w >= W / HIT_COLS}
        assert wide and wide <= reach, (n_q, sorted(wide - reach))


def test_label_box_follows_each_segment_and_slivers_lose_their_labels():
    from helao.ui.reflex.timeline_strip import (
        LABEL_MIN_PX,
        LABEL_PAD_PX,
        MIN_KEY_PX,
        strip_marks,
    )

    items = _states(*["done"] * 10, "active", *["queued"] * 30)
    marks, slots, edges = strip_marks(
        items, n_before=0, n_after=0, now=T0, width_px=W, today=TODAY
    )
    w = _widths(edges)
    texts = _texts(marks)
    assert texts and [t["max_px"] for t in texts] == pytest.approx(
        [MIN_KEY_PX - 2 * LABEL_PAD_PX] * 7
    )
    # the sliver width is (704 - 180) / 38 = 13.8 px: below the label floor
    assert w[0] - 2 * LABEL_PAD_PX < LABEL_MIN_PX
    centres = {t["x"] for t in texts}
    for i in (9, 10, 11):  # key slots only
        assert (edges[i] + edges[i + 1]) / 2 in centres
    assert len(texts) == 7  # three lines each, the queued one only its name
    # unsqueezed neighbour: narrow is per segment (a 100 px slot is not narrow)
    marks, *_ = strip_marks(
        _states(*["done"] * 7), n_before=0, n_after=0, now=T0, width_px=W, today=TODAY
    )
    assert any(t["value"] == "10:00:01" for t in _texts(marks))  # 100 px: end time


def test_progress_descriptor_only_with_an_active_slot_and_its_edges():
    from helao.ui.reflex.timeline_strip import (
        PROGRESS_W,
        PROGRESS_Y,
        SAWTOOTH_HZ,
        progress_items,
        strip_marks,
    )
    from helao.ui.shared.palette import GROUP_PROGRESS

    def items_for(*names, **kw):
        _, slots, edges = strip_marks(
            _states(*names),
            n_before=0,
            n_after=0,
            now=T0,
            width_px=W,
            today=TODAY,
            **kw,
        )
        return progress_items(slots, edges), edges

    assert items_for("done", "queued")[0] == []  # idle: none
    assert items_for()[0] == []
    got, edges = items_for(*["done"] * 10, "active", *["queued"] * 10)
    assert got == [
        {
            "x0": edges[10],
            "x1": edges[11],
            "y": PROGRESS_Y,
            "color": GROUP_PROGRESS,
            "width": PROGRESS_W,
            "hz": SAWTOOTH_HZ,
        }
    ]
    got, edges = items_for("done", "active", "active", "queued")  # parallel actives
    assert [(g["x0"], g["x1"]) for g in got] == [
        (edges[1], edges[2]),
        (edges[2], edges[3]),
    ]


def test_the_progress_descriptor_does_not_depend_on_the_clock():
    from helao.ui.reflex.timeline_strip import progress_items, strip_marks

    def at(now):
        _, slots, edges = strip_marks(
            _states("done", "active", "queued"),
            n_before=0,
            n_after=0,
            now=now,
            width_px=W,
            today=TODAY,
        )
        return progress_items(slots, edges)

    assert at(T0) == at(T0 + 0.5) == at(T0 + 3.7)


# ---- round 1: review items -----------------------------------------------------


def _row_values(marks, edges, i):
    """``{row y: text}`` drawn in slot ``i``."""
    mid = (edges[i] + edges[i + 1]) / 2
    return {t["y"]: t["value"] for t in _texts(marks) if abs(t["x"] - mid) < 1e-6}


def test_every_key_slot_keeps_its_full_label_lines_whatever_the_float_noise():
    from helao.ui.reflex.timeline_strip import TEXT_Y, strip_marks

    for n in range(12, 80):
        for p in range(n):
            names = ["done"] * p + ["active"] + ["queued"] * (n - p - 1)
            marks, slots, edges = strip_marks(
                _states(*names), n_before=0, n_after=0, now=T0, width_px=W, today=TODAY
            )
            for i in (p - 1, p, p + 1):
                if not 0 <= i < n:
                    continue
                want = {"done": 3, "active": 3, "queued": 1}[names[i]]
                got = _row_values(marks, edges, i)
                assert len(got) == want and TEXT_Y[0] in got, (n, p, i, got)
                if names[i] != "queued":
                    assert got[TEXT_Y[1]] == "10:00:00", (n, p, i, got)


def test_no_next_key_from_a_finished_slot():
    assert _keys("done", "active", "error", "queued") == {0, 1}
    assert _keys("done", "active", "queued", "queued") == {0, 1, 2}


def test_parallel_actives_are_all_key_with_one_neighbour_each_side():
    assert _keys("done", "active", "active", "queued") == {0, 1, 2, 3}
    assert _keys("done", "done", "active", "active", "queued", "queued") == {
        1,
        2,
        3,
        4,
    }
    assert _keys("active", "active") == {0, 1}
    # only the slot after the LAST active is a neighbour: a queued one between is not key
    assert _keys("done", "active", "queued", "active") == {0, 1, 3}


def test_parallel_actives_squeeze_to_the_minimum_and_overflow_falls_back():
    from helao.ui.reflex.timeline_strip import MIN_KEY_PX, slot_edges

    names = ["done"] * 6 + ["active"] * 2 + ["queued"] * 12
    w = _widths(slot_edges(_states(*names), W))
    assert w[5:9] == pytest.approx([MIN_KEY_PX] * 4) and sum(w) == pytest.approx(W)
    # 12 keys need 720 > 704: equal widths
    names = ["done"] + ["active"] * 10 + ["queued"] * 2
    assert slot_edges(_states(*names), W) == tuple(i * W / 13 for i in range(13)) + (W,)


def test_a_segment_that_cannot_fit_a_time_shows_the_name_only():
    from helao.ui.reflex.timeline_strip import (
        LABEL_PAD_PX,
        TEXT_Y,
        TIME_PX,
        strip_marks,
    )

    items = _states(*["done"] * 3, "active", *["queued"] * 9)  # slivers of 52.4 px
    for width in (W, 640.0):  # 52.4 px and 46.9 px boxes: the second is under TIME_PX
        marks, _, edges = strip_marks(
            items, n_before=0, n_after=0, now=T0, width_px=width, today=TODAY
        )
        box = _widths(edges)[0] - 2 * LABEL_PAD_PX
        got = _row_values(marks, edges, 0)
        assert (TEXT_Y[1] in got) == (box >= TIME_PX), (width, box, got)
        assert TEXT_Y[0] in got
    assert 44 <= TIME_PX <= 46
    # the threshold itself: a 52 px segment has a 44 px box and still shows the time
    marks, _, edges = strip_marks(
        items,
        n_before=0,
        n_after=0,
        now=T0,
        width_px=3 * 60 + 52 * 9 + 2 * 52,
        today=TODAY,
    )
    assert TEXT_Y[1] in _row_values(marks, edges, 0)
