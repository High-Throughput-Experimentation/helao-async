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

**Both can abort the running measurement**, through the bare private
``stop_private`` route their Bokeh twins call. That wire lives here for the same
reason the axis logic does: it is the part that can be wrong, and it must be
assertable without Reflex's app machinery.
"""

__all__ = [
    "CHANNEL_COLUMN",
    "NEGATED",
    "STOP_ROUTE",
    "STOP_TIMEOUT",
    "STOP_RETRIES",
    "axis_defaults",
    "plottable_columns",
    "xy_pair",
    "channels_in",
    "select_channel",
    "server_address",
    "stop_params",
    "stop_measurement",
]

import numpy as np

from helao.core.error import ErrorCodes
from helao.helpers import helao_logging as logging
from helao.helpers.dispatcher import async_private_dispatcher

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Routing column BioLogic packets carry. Not a measurement.
CHANNEL_COLUMN = "channel"

#: The private endpoint that aborts a running measurement, exactly as the Bokeh
#: panels call it (``servers/visualizer/gamry_vis.py`` and ``biologic_vis.py``).
#: Bare-path and ``tags=["private"]``, so it never enters the action namespace
#: and never queues behind whatever the orchestrator is running -- which is the
#: whole point of an abort.
STOP_ROUTE = "stop_private"

#: Seconds one stop call waits, and how many times it retries.
#:
#: The same reasoning as ``io_control``'s constants and the same shape: far
#: below the dispatcher's 60s/5, because this runs on a click and an operator
#: aborting a measurement needs to be told quickly that the call did not land.
#: Two attempts rather than one -- a dropped abort is worse than a slow one --
#: and no more, because a stop nobody can confirm is worth reporting rather than
#: retrying at.
STOP_TIMEOUT = 5
STOP_RETRIES = 2

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


def server_address(world_cfg: dict, server_key: str) -> tuple:
    """Look up an action server's ``(host, port)`` in the world config.

    The same lookup ``VisSubscriber.__init__`` does for the Bokeh panels
    (``vis.world_cfg["servers"][serv_key]``), so both stacks address the same
    server from the same place.

    Returns:
        tuple: ``(host, port)``, either ``None`` when the config does not
        declare it. A caller with no address must say so rather than dispatch
        to ``None`` -- a stop button that quietly does nothing is the failure
        this panel is least able to afford.
    """
    server_cfg = ((world_cfg or {}).get("servers") or {}).get(server_key) or {}
    return server_cfg.get("host"), server_cfg.get("port")


def stop_params(channel=None) -> dict:
    """Query params one ``stop_private`` call carries.

    Args:
        channel: Hardware channel to stop, or ``None`` for a single-potentiostat
            server. Accepts the string a browser event delivers.

    Returns:
        dict: ``{"channel": int}`` for a per-channel panel -- the shape
        ``biologic_vis.py``'s button sends, an int rather than the click's
        string -- and ``{}`` for Gamry, whose ``stop_private`` takes no
        arguments and stops every executor it has.
    """
    if channel is None or channel == "":
        return {}
    return {"channel": int(channel)}


async def stop_measurement(server_key: str, host: str, port: int, channel=None) -> str:
    """Abort the running measurement on one potentiostat server.

    Args:
        server_key: Config key of the action server, for logging.
        host: Its host.
        port: Its HTTP port.
        channel: Channel to stop, or ``None`` for a single potentiostat.

    Returns:
        str: Empty when the call landed, otherwise a message the panel shows.
        A failed abort must be *visible*: the operator pressed stop because the
        instrument is doing something they want it to stop doing, and a button
        that swallows its own failure tells them it worked.
    """
    if host is None or port is None:
        LOGGER.error(f"'{server_key}' has no host/port; cannot stop")
        return f"no address for '{server_key}' in the config"
    try:
        _response, error_code = await async_private_dispatcher(
            server_key=server_key,
            host=host,
            port=port,
            private_action=STOP_ROUTE,
            params_dict=stop_params(channel),
            json_dict={},
            timeout=STOP_TIMEOUT,
            retries=STOP_RETRIES,
        )
    except Exception as exc:
        LOGGER.error(f"'{server_key}' {STOP_ROUTE} failed", exc_info=True)
        return f"stop failed: {type(exc).__name__}: {exc}"
    if error_code != ErrorCodes.none:
        LOGGER.error(f"'{server_key}' {STOP_ROUTE} -> {error_code}")
        return f"stop failed: {error_code}"
    return ""
