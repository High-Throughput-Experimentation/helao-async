"""Pure marks for one /group timeline strip (experiments or actions).

Ordinal: every item is one equal-width segment on x in [0, n), whatever its
duration. A ``None`` slot is a ``+N`` ellipsis marking a cut end of the window.
Times are station-local; a date prefix appears when a time is not today.
"""

import math
from datetime import date, datetime

from helao.ui.shared.palette import (
    CHART_CHROME,
    GROUP_LABEL_COLORS,
    GROUP_PROGRESS,
    GROUP_SELECTED_OUTLINE,
    GROUP_STATE_COLORS,
)

NARROW_PX = 90
#: Clearance kept on each side of a label inside its segment.
LABEL_PAD_PX = 4.0
#: Narrowest label box worth drawing: one glyph and the ellipsis at 11 px. A
#: segment with less room than this carries no text at all (the browser cuts
#: the rest of a longer line with an ellipsis, see ``plots.marks_chart``).
LABEL_MIN_PX = 24.0
SAWTOOTH_HZ = 2.0
#: The invisible ``hit`` trace is a fixed grid of squares tiling the whole
#: strip. xy's pick is pixel-exact on a point's drawn marker (measured: with
#: 4 px circles a hover registered only on a marker and "left" a frame later),
#: so the markers must touch: 80 columns over ~700 px (8.75 px) and 3 rows
#: over ~44 px (14.7 px, a 60 px strip less its padding); 16 px squares still
#: overlap. 80 > 73, the EXP strip's maximum slot count (20 done + active + 50 queued + two ellipses), so every
#: slot owns a column. One point per segment centre answered only a hover on
#: that centre. The count never depends on the slot count, only the x
#: positions do.
HIT_COLS = 80
HIT_ROWS = 3
HIT_TRACE = "hit"
HIT_PX = 16.0


def hit_slot(index, n_slots):
    """Slot index under hit-grid point ``index`` (row-major), or None."""
    try:
        col = int(index) % HIT_COLS
    except (TypeError, ValueError):
        return None
    if int(index) < 0 or int(index) >= HIT_COLS * HIT_ROWS:
        return None
    return min(int((col + 0.5) * max(n_slots, 1) / HIT_COLS), n_slots - 1)


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
    """``(line 1, line 2)``: name, then times. Narrow: start time only.

    The name stays in narrow mode: the label box clips it with an ellipsis.
    """
    t0, t1 = item.get("t_start"), item.get("t_end")
    state = item.get("state")
    if state == "queued":
        t0 = None  # not started: no time, whatever a stale t_start says
    name = item.get("name") or ""
    if narrow:
        return name, (fmt_hms(t0, today) if t0 is not None else "")
    if t0 is None:
        return name, ""
    if state == "active":
        return name, f"{fmt_hms(t0, today)}– ({fmt_elapsed(now - t0)})"
    if t1 is None:  # finished with no end time recorded: never a running counter
        return name, f"{fmt_hms(t0, today)}–"
    return name, f"{fmt_hms(t0, today)}–{fmt_hms(t1, today)}"


def item_key(item):
    """Selection identity: the uuid, else the queue index (queued experiments)."""
    if item.get("uuid"):
        return item["uuid"]
    return f"q{item['qidx']}" if item.get("qidx") is not None else None


def click_item(slots, x):
    """The item under data-space ``x``, or None for an ellipsis or a miss."""
    if x is None or not math.isfinite(float(x)):
        return None
    i = math.floor(float(x))
    return slots[i] if 0 <= i < len(slots) else None


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


def strip_marks(items, *, n_before, n_after, now, width_px, selected=None, today=None):
    """``(marks, slots)`` for one strip; render with x_domain ``(0, max(len(slots), 1))``.

    ``width_px`` is the plot width (the host minus its padding): a segment is
    ``width_px / len(slots)`` wide and every label is boxed inside it.
    """
    today = today or date.today()
    slots = ([None] if n_before else []) + list(items) + ([None] if n_after else [])
    n = max(len(slots), 1)
    narrow = width_px / n < NARROW_PX
    box = width_px / n - 2 * LABEL_PAD_PX
    labels = box >= LABEL_MIN_PX
    bands, outlines, texts = [], [], []
    progress = {
        "kind": "line",
        "name": "progress",
        "x": [],
        "y": [],
        "color": GROUP_PROGRESS,
        "width": 4.0,
    }
    for i, it in enumerate(slots):
        cx = i + 0.5
        if it is None:
            count = n_before if (i == 0 and n_before) else n_after
            bands.append(
                {
                    "kind": "band",
                    "x0": i,
                    "x1": i + 1,
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
                "x0": i,
                "x1": i + 1,
                "color": GROUP_STATE_COLORS[state],
                "opacity": 1.0,
            }
        )
        line1, line2 = segment_label(it, now, narrow, today) if labels else ("", "")
        if line1:
            texts.append(_text(cx, 0.68, line1, GROUP_LABEL_COLORS[state], box))
        if line2:
            texts.append(_text(cx, 0.32, line2, GROUP_LABEL_COLORS[state], box))
        if state == "active":
            frac = (now * SAWTOOTH_HZ) % 1.0
            progress["x"], progress["y"] = [i, i + frac], [0.08, 0.08]
        if selected is not None and item_key(it) == selected:
            outlines += [
                _vline(i, GROUP_SELECTED_OUTLINE, 3.0),
                _vline(i + 1, GROUP_SELECTED_OUTLINE, 3.0),
            ]
    partitions = [_vline(i, CHART_CHROME["--chart-axis"], 1.0) for i in range(1, n)]
    n_hit = HIT_COLS * HIT_ROWS
    hit = {
        "kind": "scatter",
        "name": HIT_TRACE,
        "x": [
            (c + 0.5) * n / HIT_COLS for _ in range(HIT_ROWS) for c in range(HIT_COLS)
        ],
        "y": [(r + 0.5) / HIT_ROWS for r in range(HIT_ROWS) for _ in range(HIT_COLS)],
        "colors": [GROUP_STATE_COLORS["queued"]] * n_hit,
        "size": HIT_PX,
        "symbol": "square",
        "opacity": 0.0,
    }
    return bands + partitions + outlines + [progress, hit] + texts, slots
