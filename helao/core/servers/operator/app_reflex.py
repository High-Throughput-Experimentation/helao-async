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
    "server_rows",
    "status_line",
    "may_edit_queue",
    "moved_index",
    "poll_interval_for",
    "refresh_tables",
    "dispatch_control",
    "dispatch_move",
    "dispatch_remove",
    "configure",
    "reset_settings",
    "make_backend",
    "session_backend",
    "OperatorQueueState",
    "SEQ_COLS",
    "EXP_COLS",
    "ACT_COLS",
]

import asyncio
import threading
from typing import Optional

import reflex as rx

from helao.helpers import helao_logging as logging
from helao.helpers.helao_dirs import helao_dirs

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Columns shown in each queue table, mirroring the Bokeh operator's tables.
#: These are a contract with ``RemoteBackend``'s list methods, which project
#: each queue item down to a fixed key set. ``queue_rows`` renders an unknown
#: column as an empty cell rather than raising, so a name that drifts from that
#: key set produces a blank column that reads as missing orchestrator data --
#: which is why a test asserts these against the backend's own key constants.
SEQ_COLS = [
    "sequence_name",
    "sequence_label",
    "sequence_uuid",
    "campaign_name",
    "campaign_uuid",
]
EXP_COLS = ["experiment_name", "experiment_uuid"]
ACT_COLS = ["action_name", "action_server", "action_uuid"]

#: Controls the page may invoke, by ``OrchBackend`` method name. Reflex event
#: arguments arrive from the client, so this is an allow-list rather than a
#: convenience: without it a crafted event would reach any coroutine on the
#: backend, ``close`` included.
CONTROL_METHODS = frozenset(
    {
        "start",
        "stop",
        "estop",
        "skip",
        "clear_sequences",
        "clear_experiments",
        "clear_actions",
    }
)

#: Queue kind -> (move method, remove method) on the backend.
QUEUE_METHODS = {
    "sequence": ("move_sequence", "remove_sequence"),
    "experiment": ("move_experiment", "remove_experiment"),
    "action": ("move_action", "remove_action"),
}

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


def server_rows(summary: Optional[dict]) -> list:
    """Render the action-server status summary as table rows.

    Sorted by server name so the table keeps a fixed row order regardless of
    the unordered dict the backend returns -- the same reason the Bokeh
    operator sorts it.

    Args:
        summary: ``{server_name: (status, driver_status)}`` from the backend.

    Returns:
        list[list[str]]: One ``[server, status, driver]`` row per server. A
        malformed entry still gets a row: dropping it would hide a server that
        is misbehaving, which is the case the table exists for.
    """
    rows = []
    for name, value in sorted((summary or {}).items()):
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            status, driver = value[0], value[1]
        else:
            status, driver = value, ""
        rows.append(
            [
                str(name),
                "" if status is None else str(status),
                "" if driver is None else str(driver),
            ]
        )
    return rows


def poll_interval_for(world_cfg: dict, server_key: str) -> float:
    """Poll cadence for this server, in seconds.

    A non-numeric or non-positive value falls back to the default rather than
    being honoured: a typo'd YAML value must not turn into a zero-delay loop
    hammering the orchestrator.
    """
    servers = (world_cfg or {}).get("servers") or {}
    params = (servers.get(server_key) or {}).get("params") or {}
    try:
        interval = float(params.get("poll_interval", DEFAULT_POLL_INTERVAL))
    except (TypeError, ValueError):
        return DEFAULT_POLL_INTERVAL
    return interval if interval > 0 else DEFAULT_POLL_INTERVAL


async def refresh_tables(backend) -> dict:
    """Read the orchestrator state and every queue in one pass.

    Args:
        backend: An ``OrchBackend``, or ``None`` when the page is not yet
            connected.

    Returns:
        dict: State var updates. On success this carries every row list. **On
        failure it carries no row keys at all**, so the caller's last known
        queues stay on screen while the status line reports the orchestrator
        is unreachable. Blanking the tables would read as "the queue is
        empty", which is the one lie an operator must not be told.
    """
    if backend is None:
        return {
            "reachable": False,
            "orch_state": "",
            "status": status_line(None, False),
            "error": "",
        }
    try:
        state = await backend.get_orch_state()
        sequences = await backend.list_sequences()
        experiments = await backend.list_experiments()
        actions = await backend.list_actions()
        summary = await backend.get_status_summary()
    except Exception as exc:
        LOGGER.warning(f"operator poll failed: {exc}")
        return {
            "reachable": False,
            "status": status_line(None, False),
            "error": str(exc),
        }
    return {
        "reachable": True,
        "orch_state": (state or {}).get("orch_state", ""),
        "status": status_line(state, True),
        "error": "",
        "seq_rows": queue_rows(sequences, SEQ_COLS),
        "exp_rows": queue_rows(experiments, EXP_COLS),
        "act_rows": queue_rows(actions, ACT_COLS),
        "server_rows": server_rows(summary),
    }


async def dispatch_control(backend, name: str) -> str:
    """Run one orchestrator control.

    Args:
        backend: An ``OrchBackend``, or ``None``.
        name: A member of :data:`CONTROL_METHODS`.

    Returns:
        str: Empty on success, else a message for the page's error line.
    """
    if name not in CONTROL_METHODS:
        LOGGER.warning(f"operator refused control '{name}'")
        return f"unknown control '{name}'"
    if backend is None:
        return "no orchestrator connection"
    try:
        await getattr(backend, name)()
    except Exception as exc:
        LOGGER.warning(f"operator control {name} failed: {exc}")
        return f"{name} failed: {exc}"
    return ""


async def dispatch_move(backend, kind: str, position: int, direction: str, length: int):
    """Move one queue item up or down.

    A move that cannot happen -- the first item up, the last item down --
    returns success without calling the backend, so an impossible move never
    becomes a round trip that reorders nothing while the UI implies it worked.

    Returns:
        str: Empty on success or on a no-op, else a message.
    """
    methods = QUEUE_METHODS.get(kind)
    if methods is None:
        return f"unknown queue '{kind}'"
    if backend is None:
        return "no orchestrator connection"
    target = moved_index(position, direction, length)
    if target is None:
        return ""
    try:
        await getattr(backend, methods[0])(position, target)
    except Exception as exc:
        LOGGER.warning(f"operator move {kind} failed: {exc}")
        return f"move failed: {exc}"
    return ""


async def dispatch_remove(backend, kind: str, position: int, length: int) -> str:
    """Remove one queue item.

    The bounds check is not paranoia: a position comes from a rendered row
    index, and a poll can shorten the queue between render and click.

    Returns:
        str: Empty on success, else a message.
    """
    methods = QUEUE_METHODS.get(kind)
    if methods is None:
        return f"unknown queue '{kind}'"
    if backend is None:
        return "no orchestrator connection"
    if position < 0 or position >= length:
        return "that queue item is no longer there; the queue has changed"
    try:
        await getattr(backend, methods[1])(position)
    except Exception as exc:
        LOGGER.warning(f"operator remove {kind} failed: {exc}")
        return f"remove failed: {exc}"
    return ""


class _VisShim:
    """The two attributes ``RemoteBackend`` reads off a Bokeh ``Vis``.

    ``RemoteBackend`` predates this page and was written against the Bokeh
    visualizer object, but it touches only ``world_cfg`` and ``helaodirs``.
    Supplying those is cheaper and less coupled than either importing Bokeh
    here or widening the backend's constructor for a second UI.
    """

    def __init__(self, world_cfg: dict, server_key: str):
        self.world_cfg = world_cfg
        self.helaodirs = helao_dirs(world_cfg, server_key)


#: Config needed to mint a backend, set once by :func:`configure`.
_SETTINGS: dict = {}
_SETTINGS_LOCK = threading.Lock()


def configure(world_cfg: dict, server_key: str, orch_key: Optional[str] = None) -> None:
    """Record what :func:`session_backend` needs to build a backend.

    Called when the app is built, not at import: the state class exists before
    any config is loaded.
    """
    with _SETTINGS_LOCK:
        _SETTINGS.update(
            {
                "world_cfg": world_cfg,
                "server_key": server_key,
                "orch_key": orch_key,
                "poll_interval": poll_interval_for(world_cfg, server_key),
            }
        )


def reset_settings() -> None:
    """Forget the configuration. For tests."""
    with _SETTINGS_LOCK:
        _SETTINGS.clear()


def make_backend(world_cfg: dict, server_key: str, orch_key: Optional[str] = None):
    """Build a ``RemoteBackend`` for the group's orchestrator.

    Imported here rather than at module scope: ``orch_backend`` pulls in the
    experiment and sequence libraries, and this module is imported by the app
    builder well before a page is served.
    """
    from helao.core.servers.operator.orch_backend import RemoteBackend

    return RemoteBackend(
        _VisShim(world_cfg, server_key),
        orch_key=orch_key,
        poll_interval=poll_interval_for(world_cfg, server_key),
    )


def session_backend(token: str):
    """Return this session's backend, building it on first use.

    Returns ``None`` when the app has not been configured or the backend
    cannot be built -- a poll that fires first must degrade to "cannot reach
    the orchestrator", not raise inside a background event.
    """
    backend = BACKENDS.get(token)
    if backend is not None:
        return backend
    with _SETTINGS_LOCK:
        settings = dict(_SETTINGS)
    if not settings.get("world_cfg"):
        return None
    try:
        backend = make_backend(
            settings["world_cfg"], settings["server_key"], settings.get("orch_key")
        )
    except Exception as exc:
        LOGGER.warning(f"operator backend could not be built: {exc}")
        return None
    BACKENDS.put(token, backend)
    return backend


def session_poll_interval() -> float:
    """Configured poll cadence, or the default when unconfigured."""
    with _SETTINGS_LOCK:
        return _SETTINGS.get("poll_interval", DEFAULT_POLL_INTERVAL)


class OperatorQueueState(rx.State):
    """Queue tables, orchestrator status, and the controls that act on them.

    One state per tab group, not one per page: Reflex re-renders every
    component bound to a state when any of its vars change, so folding the
    parameter forms in here would re-push all four tables on every keystroke.

    Rows are never edited locally. A control calls the backend and lets the
    next poll show the result -- the orchestrator owns the queues, and a local
    edit the next poll contradicts is worse than a slower update.
    """

    # Element types are annotated rather than bare `list`: rx.foreach cannot
    # iterate a var whose element type is unknown, and that failure surfaces
    # in the frontend build, not at import.
    seq_rows: list[list[str]] = []
    exp_rows: list[list[str]] = []
    act_rows: list[list[str]] = []
    server_rows: list[list[str]] = []

    orch_state: str = ""
    status: str = "connecting to the orchestrator..."
    reachable: bool = False
    error: str = ""
    polling: bool = False

    @rx.var
    def can_edit_queue(self) -> bool:
        """Whether the queue-editing controls are enabled."""
        return self.reachable and may_edit_queue(self.orch_state)

    def _apply(self, updates: dict) -> None:
        """Assign a :func:`refresh_tables` result.

        Only the keys present are assigned, which is what preserves the last
        known rows across an unreachable poll.
        """
        for key, value in updates.items():
            setattr(self, key, value)

    @rx.event(background=True)
    async def poll_loop(self):
        """Refresh every table until the page goes away.

        Background because it sleeps: a foreground handler holding the state
        lock for the poll interval would freeze every control on the page.
        """
        async with self:
            if self.polling:
                # A remount must not start a second loop against the same
                # session; two loops would double the orchestrator's load and
                # interleave their writes.
                return
            self.polling = True
            token = self.router.session.client_token
        while True:
            backend = session_backend(token)
            updates = await refresh_tables(backend)
            async with self:
                if not self.polling:
                    return
                self._apply(updates)
            await asyncio.sleep(session_poll_interval())

    @rx.event
    def stop_polling(self):
        """End the poll loop and drop this session's backend."""
        self.polling = False
        BACKENDS.drop(self.router.session.client_token)

    @rx.event(background=True)
    async def control(self, name: str):
        """Run one orchestrator control and report any failure."""
        async with self:
            token = self.router.session.client_token
        message = await dispatch_control(session_backend(token), name)
        async with self:
            self.error = message

    @rx.event(background=True)
    async def move(self, kind: str, position: int, direction: str):
        """Move a queue item, then let the next poll show the new order."""
        async with self:
            token = self.router.session.client_token
            length = len(self._rows_for(kind))
        message = await dispatch_move(
            session_backend(token), kind, position, direction, length
        )
        async with self:
            self.error = message

    @rx.event(background=True)
    async def remove(self, kind: str, position: int):
        """Remove a queue item, then let the next poll show the new queue."""
        async with self:
            token = self.router.session.client_token
            length = len(self._rows_for(kind))
        message = await dispatch_remove(session_backend(token), kind, position, length)
        async with self:
            self.error = message

    def _rows_for(self, kind: str) -> list:
        """Currently rendered rows for one queue kind."""
        return {
            "sequence": self.seq_rows,
            "experiment": self.exp_rows,
            "action": self.act_rows,
        }.get(kind, [])
