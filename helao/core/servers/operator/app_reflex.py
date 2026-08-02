"""Reflex rendering of the standalone operator.

A second UI over the same orchestrator seam the Bokeh operator uses:
``orch_backend.OrchBackend`` is an async ABC of 25 methods, and this page is a
consumer of it, not a second implementation. That module is not changed to suit
this one -- ``bokeh_operator.py`` is still live beside it, named by 32 configs.

Two structural choices worth knowing before editing:

* **The logic that can be wrong lives in module-level functions**, because
  ``rx.State`` cannot be instantiated outside a running app. The state classes
  are var assignment and cadence only, which is what makes any of this testable.
* **State is split per tab group**, not one state for the page. Reflex
  re-renders on any var change within a state, so a single page-wide state would
  make a keystroke in a parameter field re-push every queue table. The states
  never reference each other's vars; they communicate through the backend, and
  the next poll shows the result.
"""

__all__ = [
    "BackendRegistry",
    "BACKENDS",
    "queue_rows",
    "status_line",
    "may_edit_queue",
    "moved_index",
    "SEQ_COLS",
    "EXP_COLS",
    "ACT_COLS",
]

import threading
from typing import Optional

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Columns shown in each queue table. The orchestrator returns far more per
#: item than an operator can read at a glance; these mirror the Bokeh tables.
SEQ_COLS = ["sequence_name", "sequence_label", "sequence_uuid", "status"]
EXP_COLS = ["experiment_name", "experiment_uuid", "status"]
ACT_COLS = ["action_name", "action_server_name", "action_uuid", "status"]

#: Orchestrator states in which queue reordering is safe. Editing a queue the
#: orchestrator is actively dispatching from races it, which is why the Bokeh
#: operator gates its buttons the same way.
EDITABLE_STATES = frozenset({"idle", "stopped"})

#: Seconds between orchestrator polls when the config gives no `poll_interval`.
DEFAULT_POLL_INTERVAL = 5.0


class BackendRegistry:
    """Per-session ``session_token -> OrchBackend`` map.

    The backend holds sockets and a poll task, so it cannot ride a Reflex var
    (which is serialised to JSON) and it must be closed when its page goes
    away rather than merely dereferenced.
    """

    def __init__(self):
        """Create an empty registry."""
        self._lock = threading.Lock()
        self._backends: dict = {}

    def put(self, token: str, backend) -> None:
        """Store a session's backend."""
        with self._lock:
            self._backends[token] = backend

    def get(self, token: str):
        """Return a session's backend, or ``None``."""
        with self._lock:
            return self._backends.get(token)

    def drop(self, token: str) -> None:
        """Close and forget a session's backend.

        Never raises: this runs on page unmount, where an exception would leave
        the entry in the registry forever and leak the session it holds.
        """
        with self._lock:
            backend = self._backends.pop(token, None)
        if backend is None:
            return
        close = getattr(backend, "close", None)
        if close is None:
            return
        try:
            close()
        except Exception as exc:
            LOGGER.warning(f"operator backend close failed: {exc}")


#: Process-wide registry the page reads through.
BACKENDS = BackendRegistry()


def queue_rows(items: list, columns: list) -> list:
    """Render backend queue objects as table rows.

    Every cell is a string. Reflex serialises state to JSON, and a UUID, a
    ``None``, or a nested dict reaches the browser as garbage or breaks the
    encoder outright.

    Args:
        items: Queue objects from the backend.
        columns: Column names to project, in display order.

    Returns:
        list[list[str]]: One row per item; a missing column renders empty
        rather than dropping the row, so a queue item is never invisible
        because one field is absent.
    """
    return [
        [("" if item.get(col) is None else str(item.get(col))) for col in columns]
        for item in items
    ]


def status_line(orch_state: Optional[dict], reachable: bool) -> str:
    """One line describing the orchestrator.

    ``reachable`` is tracked separately from the state because ``RemoteBackend``
    polls over HTTP and a station's orchestrator restarting mid-session is
    routine -- reporting that as "idle" would be a lie about it, and "idle" is
    exactly the state an operator reads as "safe to enqueue".

    Args:
        orch_state: The ``get_orch_state`` payload, or ``None``.
        reachable: Whether the last poll reached the orchestrator.

    Returns:
        str: The status line.
    """
    if not reachable:
        return "cannot reach the orchestrator"
    state = (orch_state or {}).get("orch_state", "unknown")
    loop = (orch_state or {}).get("loop_state", "")
    return f"orchestrator {state}" + (f" (loop {loop})" if loop else "")


def may_edit_queue(orch_state: str) -> bool:
    """Whether queue reordering and removal are safe right now.

    Args:
        orch_state: The orchestrator's reported state.

    Returns:
        bool: ``True`` only when the orchestrator is not dispatching.
    """
    return orch_state in EDITABLE_STATES


def moved_index(position: int, direction: str, length: int):
    """Target index for a queue move, or ``None`` when the move is impossible.

    Returning ``None`` rather than clamping matters: clamping turns "move the
    first item up" into a no-op the backend is still asked to perform, and the
    orchestrator would reorder nothing while the UI claimed it had.

    Args:
        position: Current index.
        direction: ``"up"`` or ``"down"``.
        length: Queue length.

    Returns:
        int | None: The target index, or ``None`` if out of range or at an end.
    """
    if position < 0 or position >= length:
        return None
    target = position - 1 if direction == "up" else position + 1
    if target < 0 or target >= length:
        return None
    return target
