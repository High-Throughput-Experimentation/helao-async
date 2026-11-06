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
SAWTOOTH_HZ = 2.0


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
    """``(line 1, line 2)``: name, then times. Narrow: start time only."""
    t0, t1 = item.get("t_start"), item.get("t_end")
    if narrow:
        return "", (fmt_hms(t0, today) if t0 is not None else "")
    name = item.get("name") or ""
    if t0 is None:
        return name, ""
    if item.get("state") == "active" or t1 is None:
        return name, f"{fmt_hms(t0, today)}– ({fmt_elapsed(now - t0)})"
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


def _text(x, y, value, color):
    return {
        "kind": "text",
        "x": x,
        "y": y,
        "value": value,
        "dx": 0.0,
        "dy": 4.0,
        "color": color,
        "anchor": "middle",
    }


def _vline(x, color, width):
    return {"kind": "vline", "x": x, "color": color, "width": width}


def strip_marks(items, *, n_before, n_after, now, width_px, selected=None, today=None):
    """``(marks, slots)`` for one strip; render with x_domain ``(0, max(len(slots), 1))``."""
    today = today or date.today()
    slots = ([None] if n_before else []) + list(items) + ([None] if n_after else [])
    n = max(len(slots), 1)
    narrow = width_px / n < NARROW_PX
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
            texts.append(_text(cx, 0.5, f"+{count}", GROUP_LABEL_COLORS["queued"]))
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
        line1, line2 = segment_label(it, now, narrow, today)
        if line1:
            texts.append(_text(cx, 0.68, line1, GROUP_LABEL_COLORS[state]))
        if line2:
            texts.append(_text(cx, 0.32, line2, GROUP_LABEL_COLORS[state]))
        if state == "active":
            frac = (now * SAWTOOTH_HZ) % 1.0
            progress["x"], progress["y"] = [i, i + frac], [0.08, 0.08]
        if selected is not None and item_key(it) == selected:
            outlines += [
                _vline(i, GROUP_SELECTED_OUTLINE, 3.0),
                _vline(i + 1, GROUP_SELECTED_OUTLINE, 3.0),
            ]
    partitions = [_vline(i, CHART_CHROME["--chart-axis"], 1.0) for i in range(1, n)]
    hit = {
        "kind": "scatter",
        "name": "hit",
        "x": [i + 0.5 for i in range(len(slots))],
        "y": [0.5] * len(slots),
        "colors": [GROUP_STATE_COLORS["queued"]] * len(slots),
        "size": 4.0,
        "symbol": "circle",
        "opacity": 0.0,
    }
    return bands + partitions + outlines + [progress, hit] + texts, slots
