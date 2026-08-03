"""Shared machinery for the hte deployment's Reflex potentiostat panels.

Gamry and BioLogic differ from the other action panels in two ways, and both
live here.

**The axes are chosen, not fixed.** A CV is read as current against potential,
a CA as current against time; plotting either on the other's axes makes the
measurement unreadable. Each panel carries a map from action name to the
default pair, and the operator can override it.

**BioLogic draws one plot pair per hardware channel.** Its packets carry a
``channel`` column that routes each row; Gamry is a single potentiostat and
streams no such column.
"""

__all__ = [
    "CHANNEL_COLUMN",
    "NEGATED",
    "axis_defaults",
    "plottable_columns",
    "xy_pair",
    "channels_in",
    "select_channel",
]

import numpy as np

#: Routing column BioLogic packets carry. Not a measurement.
CHANNEL_COLUMN = "channel"

#: Columns plotted negated, with the label to match. A Nyquist plot is -Zimag
#: against Zreal, which is what the Bokeh panel draws.
NEGATED = {"Zimag": "-Zimag"}


def axis_defaults(axis_map: dict, action_name: str, columns) -> tuple:
    """Default ``(x, y)`` column names for one technique.

    Falls back to the first two available columns when the action is not in
    the map, or when the map names a column this server never streams -- a
    new technique should still plot something, and a panel pointed at a
    missing column plots nothing with no explanation.
    """
    available = list(columns)
    if not available:
        return "", ""
    fallback_x = available[0]
    fallback_y = available[1] if len(available) > 1 else available[0]
    mapped = axis_map.get(action_name)
    if not mapped:
        return fallback_x, fallback_y
    x, y = mapped
    if x not in available or y not in available:
        return fallback_x, fallback_y
    return x, y


def plottable_columns(snapshot: dict, declared) -> list:
    """Columns worth offering as axes, declared ones first.

    A panel declares the columns its server streams, but the stream is the
    authority: a technique that reports something else entirely would
    otherwise leave the panel choosing axes that are not there, which draws a
    blank chart. Anything the stream carries beyond the declared set is
    appended rather than dropped, so the panel can still plot -- and the
    caller can tell the operator that is what happened.

    The channel column is excluded: it routes rows, it is not a measurement.
    """
    declared_present = [c for c in declared if c in snapshot]
    extra = [
        c
        for c in snapshot
        if c != CHANNEL_COLUMN and c not in declared_present and c not in declared
    ]
    return declared_present + extra


def xy_pair(snapshot: dict, x_column: str, y_column: str) -> tuple:
    """Take one x and one y column out of a snapshot.

    Returns:
        tuple: ``(x, {label: y})``. Either being absent yields an empty
        series rather than raising -- a missing column must not take the
        whole panel down from inside the render.
    """
    x = snapshot.get(x_column)
    y = snapshot.get(y_column)
    if x is None or y is None:
        return np.empty(0) if x is None else x, {}
    label = NEGATED.get(y_column)
    return x, {label: -y} if label else {y_column: y}


def channels_in(snapshot: dict) -> list:
    """Hardware channels present in the window, sorted.

    Empty for a server that streams no channel column, which is how a
    single-potentiostat panel is told it has exactly one plot to draw.
    """
    channel = snapshot.get(CHANNEL_COLUMN)
    if channel is None or channel.size == 0:
        return []
    return sorted({int(v) for v in channel if np.isfinite(v)})


def select_channel(snapshot: dict, channel: int) -> dict:
    """Rows belonging to one channel, without the routing column.

    A snapshot with no channel column is returned whole: it came from a
    single-channel instrument.
    """
    routing = snapshot.get(CHANNEL_COLUMN)
    if routing is None:
        return dict(snapshot)
    mask = routing == channel
    return {
        name: values[mask]
        for name, values in snapshot.items()
        if name != CHANNEL_COLUMN
    }
