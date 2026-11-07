"""Pure marks for one /group timeline strip (experiments or actions).

Ordinal: every item is one segment, whatever its duration, on an x axis in
pixels ``[0, width_px]``. Segments are equal while they all fit ``MIN_KEY_PX``;
otherwise the key slots (see ``key_indices``) keep that width and the rest
share what is left. A ``None`` slot is a ``+N`` ellipsis marking a cut end of
the window.
Times are station-local; a date prefix appears when a time is not today.
"""

import math
from bisect import bisect_right
from datetime import date, datetime

from helao.ui.shared.palette import (
    CHART_CHROME,
    GROUP_LABEL_COLORS,
    GROUP_PROGRESS,
    GROUP_SELECTED_OUTLINE,
    GROUP_STATE_COLORS,
)

#: Width kept by each key slot (active, previous, next) once the strip is too
#: crowded for equal segments, and the width below which a segment shows only
#: its start time. Derived in the browser (11 px system-ui): the widest
#: "HH:MM:SS" is 43.7 px, plus the 2 x 4 px label pad is 51.7, rounded up to
#: 60. A date-prefixed time ("MM-DD HH:MM:SS", 75.2 px) does not fit and is
#: clipped with an ellipsis, which is acceptable because it is rare.
MIN_KEY_PX = 60.0
NARROW_PX = MIN_KEY_PX
#: Room one "HH:MM:SS" needs inside a label box: measured 43.7 px (11 px
#: system-ui), rounded up. A segment whose box (width less 2 x LABEL_PAD_PX)
#: is narrower shows the name only, so a clipped "07:33..." never appears.
TIME_PX = 44.0
#: Clearance kept on each side of a label inside its segment.
LABEL_PAD_PX = 4.0
#: Narrowest label box worth drawing: one glyph and the ellipsis at 11 px. A
#: segment with less room than this carries no text at all (the browser cuts
#: the rest of a longer line with an ellipsis, see ``plots.marks_chart``).
LABEL_MIN_PX = 24.0
#: Sweeps per second of the active slot's progress bar. The bar is animated in
#: the browser (see ``xy_component``), so this is a frame-rate-smooth rate, not
#: something the 2 Hz page tick samples.
SAWTOOTH_HZ = 2.0
#: Bar thickness in px and its height in plot fractions: centred 2 px above the
#: plot bottom, so it sits under the label rows (measured with xy's label
#: placement, the bottom row's glyphs end ~6 px above the plot bottom).
PROGRESS_W = 4.0
PROGRESS_Y = 0.0455
#: Rows of a three-line label (name, start, end), in plot fractions from the
#: bottom; the progress bar sits below them (``PROGRESS_Y``).
TEXT_Y = (0.82, 0.54, 0.26)
#: The invisible ``hit`` trace is a fixed grid of squares tiling the whole
#: strip. xy's pick is pixel-exact on a point's drawn marker (measured: with
#: 4 px circles a hover registered only on a marker and "left" a frame later),
#: so the markers must touch: 80 columns over ~700 px (8.75 px) and 3 rows
#: over ~44 px (14.7 px, a 60 px strip less its padding); 16 px squares still
#: overlap. 80 > 73, the EXP strip's maximum slot count (20 done + active + 50
#: queued + two ellipses), so while the strip is not squeezed every slot owns
#: a column. One point per segment centre answered only a hover on
#: that centre. The columns are spaced uniformly across the plot width and a
#: column maps to the slot whose span holds its centre, so a slot at least one
#: column wide (8.8 px) is always reachable; a squeezed sliver narrower than
#: that may own no column and cannot be hovered (accepted).
HIT_COLS = 80
HIT_ROWS = 3
HIT_TRACE = "hit"
HIT_PX = 16.0


def _slot_at(edges, x):
    """Slot whose ``[x0, x1)`` holds ``x``, or None outside ``[0, edges[-1])``."""
    if not 0 <= x < edges[-1]:
        return None
    return min(bisect_right(edges, x) - 1, len(edges) - 2)


def hit_slot(index, edges):
    """Slot index under hit-grid point ``index`` (row-major), or None."""
    try:
        col = int(index) % HIT_COLS
    except (TypeError, ValueError):
        return None
    if int(index) < 0 or int(index) >= HIT_COLS * HIT_ROWS:
        return None
    return _slot_at(edges, (col + 0.5) * edges[-1] / HIT_COLS)


def item_tooltip(item, now, today=None):
    """One line for a hovered segment: name, then start/end (same format as labels)."""
    if item is None:
        return ""
    today = today or date.today()
    name = item.get("name") or "?"
    state, t0, t1 = item.get("state"), item.get("t_start"), item.get("t_end")
    if state == "queued":
        return f"{name}: queued"
    if t0 is None:
        return name
    start = fmt_hms(t0, today)
    if state == "active":
        return f"{name}: start {start}, running ({fmt_elapsed(now - t0)})"
    end = fmt_hms(t1, today) if t1 is not None else "—"
    return f"{name}: start {start}, end {end}"


def fmt_hms(t, today):
    d = datetime.fromtimestamp(t)
    hms = d.strftime("%H:%M:%S")
    return hms if d.date() == today else d.strftime("%m-%d ") + hms


def fmt_elapsed(sec):
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def segment_label(item, now, narrow, today):
    """``(line 1, line 2, line 3)``: name, start time, end time or elapsed.

    Done: start, end (``—`` when none was recorded). Active: start, then the
    elapsed time in parentheses. Queued: the name only. Narrow: the name and
    the start time only. The name stays in narrow mode: the label box clips it
    with an ellipsis.
    """
    t0, t1 = item.get("t_start"), item.get("t_end")
    state = item.get("state")
    name = item.get("name") or ""
    if state == "queued" or t0 is None:  # not started: no time, whatever t_start says
        return name, "", ""
    start = fmt_hms(t0, today)
    if narrow:
        return name, start, ""
    if state == "active":
        return name, start, f"({fmt_elapsed(now - t0)})"
    return name, start, fmt_hms(t1, today) if t1 is not None else "—"


def item_key(item):
    """Selection identity: the uuid, else the queue index (queued experiments)."""
    if item.get("uuid"):
        return item["uuid"]
    return f"q{item['qidx']}" if item.get("qidx") is not None else None


def click_item(slots, edges, x):
    """The item under pixel ``x``, or None for an ellipsis or a miss."""
    if x is None or not math.isfinite(float(x)):
        return None
    i = _slot_at(edges, float(x))
    return slots[i] if i is not None and i < len(slots) else None


def _is(it, *states):
    return it is not None and it.get("state") in states


def _finished(it):
    return (
        it is not None
        and not _is(it, "active", "queued")
        and (it.get("state") in GROUP_STATE_COLORS)
    )


def key_indices(slots):
    """Slots that keep ``MIN_KEY_PX``: every active one, plus its neighbours.

    The neighbours are the finished slot just before the first active one and
    the queued slot just after the last. With no active item the last
    finished one takes the active role. A missing role is absent; ``+N``
    slots (None) are never key.
    """
    roles = [i for i, it in enumerate(slots) if _is(it, "active")]
    if not roles:
        roles = [
            next((i for i in reversed(range(len(slots))) if _finished(slots[i])), None)
        ]
        roles = [i for i in roles if i is not None]
    keys = set(roles)
    if roles and roles[0] and _finished(slots[roles[0] - 1]):
        keys.add(roles[0] - 1)
    nxt = roles[-1] + 1 if roles else 0
    if (
        nxt < len(slots)
        and slots[nxt] is not None
        and not _finished(slots[nxt])
        and (not _is(slots[nxt], "active"))
    ):
        keys.add(nxt)
    return keys


def slot_edges(slots, width_px):
    """Cumulative pixel edges (``len(slots) + 1`` of them, ``0`` to ``width_px``)."""
    n = max(len(slots), 1)
    keys = key_indices(slots)
    if width_px / n >= MIN_KEY_PX or len(keys) * MIN_KEY_PX > width_px:
        return tuple(i * width_px / n for i in range(n)) + (float(width_px),)
    rest = (width_px - len(keys) * MIN_KEY_PX) / (n - len(keys))
    edges, x = [0.0], 0.0
    for i in range(n - 1):
        x += MIN_KEY_PX if i in keys else rest
        edges.append(x)
    edges.append(float(width_px))
    return tuple(edges)


def _text(x, y, value, color, max_px):
    return {
        "kind": "text",
        "x": x,
        "y": y,
        "value": value,
        "dx": 0.0,
        "dy": 4.0,
        "color": color,
        "anchor": "middle",
        "max_px": max_px,
    }


def _vline(x, color, width):
    return {"kind": "vline", "x": x, "color": color, "width": width}


def progress_items(slots, edges):
    """One browser-animated progress bar descriptor per active slot."""
    return [
        {
            "x0": edges[i],
            "x1": edges[i + 1],
            "y": PROGRESS_Y,
            "color": GROUP_PROGRESS,
            "width": PROGRESS_W,
            "hz": SAWTOOTH_HZ,
        }
        for i, it in enumerate(slots)
        if _is(it, "active")
    ]


def strip_marks(items, *, n_before, n_after, now, width_px, selected=None, today=None):
    """``(marks, slots, edges)`` for one strip; render with x_domain ``(0, width_px)``.

    ``width_px`` is the plot width (the host minus its padding). ``edges`` are
    the slots' pixel edges (see ``slot_edges``); every label is boxed inside
    its own segment.
    """
    today = today or date.today()
    slots = ([None] if n_before else []) + list(items) + ([None] if n_after else [])
    edges = slot_edges(slots, width_px)
    bands, outlines, texts = [], [], []
    for i, it in enumerate(slots):
        x0, x1 = edges[i], edges[i + 1]
        cx = (x0 + x1) / 2
        box = x1 - x0 - 2 * LABEL_PAD_PX
        labels = box >= LABEL_MIN_PX
        if it is None:
            count = n_before if (i == 0 and n_before) else n_after
            bands.append(
                {
                    "kind": "band",
                    "x0": x0,
                    "x1": x1,
                    "color": GROUP_STATE_COLORS["queued"],
                    "opacity": 1.0,
                }
            )
            if labels:
                texts.append(
                    _text(cx, 0.5, f"+{count}", GROUP_LABEL_COLORS["queued"], box)
                )
            continue
        state = it.get("state")
        if state not in GROUP_STATE_COLORS:
            state = "queued"
        bands.append(
            {
                "kind": "band",
                "x0": x0,
                "x1": x1,
                "color": GROUP_STATE_COLORS[state],
                "opacity": 1.0,
            }
        )
        lines = (
            segment_label(it, now, round(x1 - x0, 6) < NARROW_PX, today)
            if labels
            else ("", "", "")
        )
        if box < TIME_PX:
            lines = (lines[0], "", "")
        for y, line in zip(TEXT_Y, lines):
            if line:
                texts.append(_text(cx, y, line, GROUP_LABEL_COLORS[state], box))
        if selected is not None and item_key(it) == selected:
            outlines += [
                _vline(x0, GROUP_SELECTED_OUTLINE, 3.0),
                _vline(x1, GROUP_SELECTED_OUTLINE, 3.0),
            ]
    partitions = [_vline(e, CHART_CHROME["--chart-axis"], 1.0) for e in edges[1:-1]]
    n_hit = HIT_COLS * HIT_ROWS
    hit = {
        "kind": "scatter",
        "name": HIT_TRACE,
        "x": [
            (c + 0.5) * width_px / HIT_COLS
            for _ in range(HIT_ROWS)
            for c in range(HIT_COLS)
        ],
        "y": [(r + 0.5) / HIT_ROWS for r in range(HIT_ROWS) for _ in range(HIT_COLS)],
        "colors": [GROUP_STATE_COLORS["queued"]] * n_hit,
        "size": HIT_PX,
        "symbol": "square",
        "opacity": 0.0,
    }
    return bands + partitions + outlines + [hit] + texts, slots, edges
