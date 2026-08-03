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
"""

__all__ = [
    "X_COLUMN",
    "CURRENT_PATTERN",
    "VOLTAGE_PATTERN",
    "split_on_restart",
    "cell_numbers",
    "select_cells",
    "latest_action_uuid",
]

import re

import numpy as np

#: Elapsed-seconds column every ws_data packet carries. Also the x axis.
X_COLUMN = "t_s"

#: Per-cell column names the NI-DAQmx server streams.
CURRENT_PATTERN = re.compile(r"^Icell(\d+)_A$")
VOLTAGE_PATTERN = re.compile(r"^Ecell(\d+)_V$")


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
