"""Shared machinery for the hte deployment's Reflex action panels.

``ws_data`` panels are per-action rather than continuous: each action produces
its own trace, and the Bokeh originals show the running action beside the one
before it. Two pieces of logic serve that and live here.

**Action boundaries.** The ring buffer holds numeric columns only, and the row
store beside it keeps one row per *message* -- so the ``action_uuid`` cannot be
aligned with buffer rows to segment history by action. ``t_s`` is elapsed
seconds within one action, so a decrease in it is the boundary, and it is the
only marker actually present in the data.

**Cell selection.** The NI-DAQmx server streams one current and one voltage
column per cell. Which cells to draw is an operator choice, so the columns are
discovered from the stream rather than assumed, and filtered by selection.

**Muted text.** One shade for every panel's secondary caption, here rather than
repeated per module, so the four panels cannot drift apart.
"""

__all__ = [
    "X_COLUMN",
    "CURRENT_PATTERN",
    "VOLTAGE_PATTERN",
    "MUTED_TEXT",
    "split_on_restart",
    "segment_trace_groups",
    "segment_traces",
    "cell_numbers",
    "select_cells",
    "latest_action_uuid",
]

import re

import numpy as np

from helao.ui.shared.palette import reflex_muted_text_class

#: Muted-caption Tailwind utility, resolved once at module scope per
#: ``palette``'s second rule. ``slate-600``, not the ``slate-500`` that clears
#: AA on white: these panels render on the ``/action`` route's ``violet-50``
#: canvas, where ``slate-500`` measures 4.34 and fails the 4.5 body floor.
MUTED_TEXT = reflex_muted_text_class()

#: Elapsed-seconds column every ws_data packet carries. Also the x axis.
X_COLUMN = "t_s"

#: Per-cell column names the NI-DAQmx server streams.
CURRENT_PATTERN = re.compile(r"^Icell(\d+)_A$")
VOLTAGE_PATTERN = re.compile(r"^Ecell(\d+)_V$")

#: Trace-name suffixes distinguishing the two action segments in one chart,
#: current first. They were chart headings when each segment had its own
#: chart; now they are what tells the two traces apart in the legend.
SEGMENT_LABELS = ("this action", "previous action")


def split_on_restart(x: np.ndarray, series: dict) -> tuple:
    """Split a window into the previous action and the current one.

    ``t_s`` restarts at each action, so the last position where it decreases
    is the boundary. Everything before it belongs to the previous action and
    everything from it on to the current one.

    Args:
        x: The ``t_s`` column.
        series: ``{name: np.ndarray}``, each the same length as ``x``.

    Returns:
        tuple: ``((prev_x, prev_series), (cur_x, cur_series))``. The previous
        half is empty when the window holds only one action.
    """
    if x.size == 0:
        return (x, {}), (x, dict(series))
    starts = np.flatnonzero(np.diff(x) < 0) + 1
    if starts.size == 0:
        return (np.empty(0), {}), (x, dict(series))
    current_from = int(starts[-1])
    # The previous half is the action *before* the current one, not all history
    # before it: the Bokeh panel snapshots one action into prev_datasource, so
    # a window holding three actions must not draw two of them as "previous".
    previous_from = int(starts[-2]) if starts.size > 1 else 0
    previous = (
        x[previous_from:current_from],
        {name: v[previous_from:current_from] for name, v in series.items()},
    )
    current = (
        x[current_from:],
        {name: v[current_from:] for name, v in series.items()},
    )
    return previous, current


def segment_trace_groups(
    x, series: dict, pick, labels=SEGMENT_LABELS, suffix_names: bool = True
) -> list:
    """Group traces by action segment, current first.

    The primitive behind :func:`segment_traces`. A panel drawing both segments
    in one chart flattens these groups; a panel drawing a chart per segment
    keeps them apart and titles each chart with the segment's label, in which
    case the suffix on each trace name is redundant -- pass
    ``suffix_names=False``.

    Args:
        x: The ``t_s`` column for the whole window.
        series: ``{name: np.ndarray}``, each the same length as ``x``.
        pick: ``(segment_x, segment_series) -> (x, {label: y})``, applied per
            segment. Column selection has to run after the split.
        labels: Segment labels, current first.
        suffix_names: Append ``" (<label>)"`` to each trace name.

    Returns:
        list: ``[(label, [{"label", "x", "y"}, ...]), ...]``.
    """
    previous, current = split_on_restart(x, series)
    groups = []
    for suffix, (segment_x, segment) in zip(labels, (current, previous)):
        picked_x, picked = pick(segment_x, segment)
        groups.append(
            (
                suffix,
                [
                    {
                        "label": f"{name} ({suffix})" if suffix_names else name,
                        "x": picked_x,
                        "y": values,
                    }
                    for name, values in picked.items()
                ],
            )
        )
    return groups


def segment_traces(x, series: dict, pick, labels=SEGMENT_LABELS) -> list:
    """Build one chart's traces covering both the current action and the last.

    A figure used to be drawn as two charts side by side, one per segment.
    Each chart is a WebGL canvas and so a WebGL context, browsers cap how many
    may be live at once, and a full action page ran past that cap -- Chrome
    warns "Too many active WebGL contexts. Oldest context will be lost", then
    evicts one. An evicted chart stops drawing for good while every other
    signal still reads healthy: data arrives, the view is mounted, the append
    fires, and ``_applyAppend`` returns at its ``_glLost`` guard before it
    touches the GPU. Drawing both segments as traces in one chart halves the
    contexts a panel costs.

    The two segments cannot share an x axis -- they are different lengths --
    so this returns per-trace x/y for :func:`plots.traces` rather than the
    single shared x :func:`plots.time_series` takes.

    Args:
        x: The ``t_s`` column for the whole window.
        series: ``{name: np.ndarray}``, each the same length as ``x``.
        pick: ``(segment_x, segment_series) -> (x, {label: y})``, applied per
            segment. Column selection has to run after the split, because
            which columns are wanted is the caller's business (an axis pair
            for a potentiostat, a cell subset for the cell panel).
        labels: Suffixes for the current and previous segments, in that order.

    Returns:
        list: ``[{"label", "x", "y"}]``. Current first, so it takes the first
        palette color and stays the dominant trace.
    """
    return [
        trace
        for _, traces in segment_trace_groups(x, series, pick, labels)
        for trace in traces
    ]


def cell_numbers(series: dict, pattern: re.Pattern) -> list:
    """Cell numbers present in ``series`` for one column pattern.

    Sorted numerically, not lexically: ``Icell10_A`` sorts before ``Icell2_A``
    as text, which would scramble the legend and the selector.
    """
    found = []
    for name in series:
        match = pattern.match(name)
        if match:
            found.append(int(match.group(1)))
    return sorted(found)


def select_cells(series: dict, pattern: re.Pattern, cells) -> dict:
    """Keep only the columns for the selected cells.

    An empty selection yields nothing to plot, which is a legitimate operator
    choice rather than an error.
    """
    wanted = set(cells)
    picked = {}
    for name, values in series.items():
        match = pattern.match(name)
        if match and int(match.group(1)) in wanted:
            picked[name] = values
    return picked


def latest_action_uuid(ingest) -> str:
    """The action UUID of the most recent packet, or ``""``."""
    latest = ingest.rows.latest() or {}
    return str(latest.get("action_uuid", ""))
