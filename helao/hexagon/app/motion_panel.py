"""Server-side helpers shared by the motion servers' private panel routes.

Whether an action is running is knowable only server-side, from the ``Base``
object no shared UI module holds, so these live here rather than beside the
panel logic in ``helao/ui/shared/motion_control.py`` -- only the *rendering*
of a refusal does.
"""

import asyncio
from typing import Optional

from helao.core.error import ErrorCodes

__all__ = [
    "PANEL_MOVE_TASKS",
    "dispatch_panel_move",
    "first_count",
    "first_error",
    "running_actions",
]


def running_actions(app) -> list:
    """Names of this server's endpoints that currently have a running action.

    Same sweep the queueing middleware performs in ``base_api.py``, without its
    single-endpoint narrowing: a panel command for the stage cares that the
    server is moving something, not which route was asked to move it.
    """
    return [ep for ep, em in app.actionservermodel.endpoints.items() if em.active_dict]


def first_error(err_code) -> ErrorCodes:
    """Collapse ``_motor_move``'s per-axis error list to a single code.

    The driver reports one code per requested axis; these endpoints request
    exactly one, but the early-refusal branches return a bare code rather than
    a list, so both shapes arrive here. The first non-``none`` entry wins --
    a partial success on a single-axis move is still a failed move.
    """
    if isinstance(err_code, list):
        for code in err_code:
            if code != ErrorCodes.none:
                return code
        return ErrorCodes.none if err_code else ErrorCodes.unspecified
    return err_code if err_code is not None else ErrorCodes.unspecified


def first_count(counts) -> Optional[int]:
    """Pull the commanded count out of ``_motor_move``'s per-axis list.

    ``None`` -- never ``0`` -- when the driver did not report one: zero is a
    legitimate count, so a missing value shown as zero would read as a
    deliberate no-op move.
    """
    if isinstance(counts, list):
        counts = counts[0] if counts else None
    if counts is None:
        return None
    try:
        return int(counts)
    except (TypeError, ValueError):
        return None


#: Panel moves currently in flight. A strong reference has to be held: the
#: event loop keeps only a weak one to a running task, so a bare
#: ``create_task`` whose result nobody stores can be collected mid-move.
PANEL_MOVE_TASKS: set = set()


def dispatch_panel_move(coro, axis: str, value: float, units: str, logger):
    """Run a panel move in the background and report what it eventually did.

    The endpoint that calls this has already answered the panel, so this
    callback is the only place a later failure can surface. Both failure
    shapes are covered, and the second is the common one:

    * an exception -- which without a done-callback becomes "Task exception
      was never retrieved" at collection time, i.e. nothing an operator sees;
    * a non-``none`` ``ErrorCodes`` in the returned dict, which is how
      ``_motor_move`` reports nearly every real fault. An exception-only
      callback would swallow those silently.

    The completed count is logged too. It used to be in the endpoint's return
    payload and cannot be now, so the log is where it lives.

    ``logger`` is the caller's module ``LOGGER``, passed at call time so each
    server logs under its own name.
    """
    task = asyncio.create_task(coro)
    PANEL_MOVE_TASKS.add(task)

    def _report(finished: asyncio.Task) -> None:
        PANEL_MOVE_TASKS.discard(finished)
        what = f"panel move on axis '{axis}' to {value} {units}"
        if finished.cancelled():
            logger.error(f"{what} was cancelled before it completed")
            return
        exc = finished.exception()
        if exc is not None:
            logger.error(f"{what} raised {exc!r}", exc_info=exc)
            return
        result = finished.result() or {}
        error_code = first_error(result.get("err_code"))
        if error_code != ErrorCodes.none:
            logger.error(f"{what} -> {error_code}")
        else:
            logger.info(f"{what} completed, counts={first_count(result.get('counts'))}")

    task.add_done_callback(_report)
    return task
