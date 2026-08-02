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
    "align_defaults",
    "field_kind",
    "fields_for_item",
    "flatten_fields",
    "field_options",
    "coerce_params",
    "version_text",
    "library_items",
    "item_by_name",
    "enqueue_sequence",
    "build_sequence",
    "build_manual_sequence",
    "custom_positions",
    "options_map_for",
    "plan_rows",
    "plan_moved",
    "plan_removed",
    "dispatch_plan",
    "history_rows",
    "HIST_COLS",
    "plate_api_for",
    "platemap_points",
    "nearest_sample",
    "composition_text",
    "sample_summary",
    "OperatorQueueState",
    "OperatorLibState",
    "OperatorPlanState",
    "OperatorPlateState",
    "SEQ_COLS",
    "EXP_COLS",
    "ACT_COLS",
]

import asyncio
import threading
from typing import Optional

import reflex as rx

from helao.core.servers.reflex import plots
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


# -- parameter forms ---------------------------------------------------------


def align_defaults(args: list, defaults: list) -> list:
    """Pad ``defaults`` at the front so it lines up with ``args``.

    Python puts parameters without defaults first, so the shorter defaults
    list belongs at the *end*. Padding the other end would hand every field
    its neighbour's default -- which the Bokeh operator avoids the same way.
    """
    padded = list(defaults)
    for _ in range(len(args) - len(padded)):
        padded.insert(0, "")
    return padded


def field_kind(argtype, options: list) -> str:
    """Input kind for one parameter: ``select``, ``bool``, ``number``, ``text``.

    ``text`` is the fallback for anything without a usable annotation, and for
    containers -- a list or dict has no typed input, so it is edited as its
    repr and parsed back on enqueue, exactly as the Bokeh operator does.
    """
    if options:
        return "select"
    # bool before int: bool is a subclass of int, so the number test would
    # claim every checkbox.
    if argtype is bool:
        return "bool"
    if argtype in (int, float):
        return "number"
    return "text"


def fields_for_item(item: dict, options_map: Optional[dict] = None) -> list:
    """Describe every input the selected library item needs.

    Args:
        item: One entry from :func:`param_forms.build_lib`. The framework-
            injected ``Experiment`` argument is already filtered out there.
        options_map: Optional ``arg name -> options`` for the parameters that
            render as a dropdown (the station's custom positions).

    Returns:
        list[dict]: ``name``, ``kind``, ``default`` (a string, as shown),
        ``help``, ``options``, and ``argtype`` (kept for coercion, and the
        reason these are dicts rather than the flattened rows the UI binds).
    """
    from helao.core.servers.operator.param_forms import parse_arg_docs

    options_map = options_map or {}
    args = list(item.get("args") or [])
    defaults = align_defaults(args, list(item.get("defaults") or []))
    argtypes = list(item.get("argtypes") or [])
    descriptions = parse_arg_docs(item.get("doc", ""))

    fields = []
    for idx, name in enumerate(args):
        argtype = argtypes[idx] if idx < len(argtypes) else "unspecified"
        options = [str(o) for o in (options_map.get(name) or [])]
        shown = str(defaults[idx])
        kind = field_kind(argtype, options)
        if kind == "select" and shown not in options:
            # Bokeh picks the first option rather than leaving a dropdown
            # displaying a value it cannot offer.
            shown = options[0]
        fields.append(
            {
                "name": name,
                "kind": kind,
                "default": shown,
                "help": descriptions.get(name, ""),
                "options": options,
                "argtype": argtype,
            }
        )
    return fields


def flatten_fields(fields: list) -> list:
    """Flatten field descriptors to the rows the UI iterates.

    ``rx.foreach`` needs a concrete element type and cannot iterate dicts with
    heterogeneous value types, so the rendered form binds
    ``list[list[str]]`` -- ``[name, kind, default, help]`` -- while the typed
    descriptors stay server-side for coercion.
    """
    return [[f["name"], f["kind"], f["default"], f["help"]] for f in fields]


def field_options(fields: list) -> list:
    """Dropdown options per field, index-parallel to :func:`flatten_fields`."""
    return [list(f["options"]) for f in fields]


def _to_bool(raw):
    """Read a checkbox value.

    ``str(False)`` is ``"False"`` and ``bool("False")`` is ``True``, so routing
    a checkbox through the plain builtin cast inverts every unchecked box.
    """
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off"):
        return False
    raise ValueError(f"'{raw}' is not a yes/no value")


def coerce_params(fields: list, values: dict) -> tuple:
    """Turn entered text into typed parameters.

    Args:
        fields: Descriptors from :func:`fields_for_item`.
        values: ``name -> entered value``. A field the operator did not touch
            falls back to its default.

    Returns:
        tuple: ``(params, errors)``. A value that will not convert is
        **reported and omitted from params**, never silently dropped: running
        a sequence with a default the operator did not choose is worse than
        not running it, and the caller refuses to enqueue while errors exist.
    """
    from helao.core.servers.operator.param_forms import BUILTIN_TYPES
    from helao.helpers.to_json import parse_bokeh_input

    params = {}
    errors = []
    for field in fields:
        name = field["name"]
        raw = values.get(name, field["default"])
        try:
            if field["kind"] == "bool":
                params[name] = _to_bool(raw)
                continue
            value = parse_bokeh_input(raw) if isinstance(raw, str) else raw
            argtype = field["argtype"]
            params[name] = argtype(value) if argtype in BUILTIN_TYPES else value
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return params, errors


def version_text(item: dict) -> str:
    """Version and codehash of a library item, as one line of plain text."""
    from helao.core.servers.operator.param_forms import version_hint_parts

    return " · ".join(version_hint_parts(item))


# -- libraries ---------------------------------------------------------------

#: Library kind -> (backend lib attribute, codehash attribute, config section,
#: name field). The experiment library additionally filters out the framework's
#: injected ``Experiment`` argument, which is resolved in `library_items`
#: because importing the model at module scope is not worth the load cost.
LIBRARY_KINDS = {
    "sequence": ("sequence_lib", "sequence_codehash", "sequence_params"),
    "experiment": ("experiment_lib", "experiment_codehash", "experiment_params"),
}


def library_items(backend, kind: str, world_cfg: dict) -> tuple:
    """Introspect one of the backend's libraries into selectable items.

    Returns:
        tuple: ``(items, names)``, both empty when there is no backend or the
        kind is unknown -- the page renders an empty selector rather than
        failing, since a backend can be absent for a whole poll cycle.
    """
    from helao.core.servers.operator.param_forms import LibItem, build_lib

    spec = LIBRARY_KINDS.get(kind)
    if backend is None or spec is None:
        if spec is None:
            LOGGER.warning(f"operator asked for unknown library kind '{kind}'")
        return [], []
    lib_attr, hash_attr, config_key = spec
    filter_type = None
    if kind == "experiment":
        from helao.helpers.premodels import Experiment

        filter_type = Experiment
    try:
        return build_lib(
            getattr(backend, lib_attr, {}) or {},
            filter_type,
            config_key,
            world_cfg or {},
            (world_cfg or {}).get("loaded_config_path", ""),
            LibItem,
            f"{kind}_name",
            codehash_map=getattr(backend, hash_attr, {}) or {},
        )
    except Exception as exc:
        LOGGER.exception(f"operator could not build the {kind} library: {exc}")
        return [], []


def item_by_name(items: list, kind: str, name: str):
    """Find a library item by its name, or ``None``.

    ``None`` is a real case, not a guard: a library reload can drop the item
    the selector is still showing.
    """
    field = f"{kind}_name"
    for item in items or []:
        if item.get(field) == name:
            return item
    return None


def build_sequence(
    backend, item, fields: list, values: dict, label: str = "", campaign: str = ""
) -> tuple:
    """Unpack the selected sequence with the entered parameters.

    Returns:
        tuple: ``(sequence, error)``. Exactly one is meaningful. Building is
        separate from dispatching because the plan tab buffers sequences
        client-side before any of them reach the orchestrator.
    """
    from helao.helpers.premodels import Sequence

    if item is None:
        return None, "no sequence is selected"
    if backend is None:
        return None, "no orchestrator connection"
    name = item.get("sequence_name", "")
    params, errors = coerce_params(fields, values)
    if errors:
        return None, "; ".join(errors)
    try:
        planned = backend.unpack_sequence(sequence_name=name, sequence_params=params)
    except Exception as exc:
        # Named, because the alternative the operator sees is a button that
        # does nothing.
        LOGGER.exception(f"operator could not unpack sequence '{name}': {exc}")
        return None, f"{name} could not be unpacked: {exc}"
    sequence = Sequence(
        sequence_name=name,
        sequence_params=params,
        sequence_label=label or None,
        planned_experiments=planned,
    )
    if campaign:
        sequence.campaign_name = campaign
    return sequence, ""


def build_manual_sequence(
    item, fields: list, values: dict, label: str = "", campaign: str = ""
) -> tuple:
    """Wrap one experiment as a single-experiment ``manual_orch_seq``.

    The orchestrator's queue takes sequences, so this is how a bare experiment
    reaches it -- the same wrapper the Bokeh operator's "append experiment"
    builds, ``manual_action`` included.

    Returns:
        tuple: ``(sequence, error)``.
    """
    from helao.helpers.premodels import Experiment, Sequence

    if item is None:
        return None, "no experiment is selected"
    name = item.get("experiment_name", "")
    params, errors = coerce_params(fields, values)
    if errors:
        return None, "; ".join(errors)
    sequence = Sequence(
        sequence_name="manual_orch_seq",
        sequence_label=label or None,
        planned_experiments=[
            Experiment(experiment_name=name, experiment_params=params)
        ],
        manual_action=True,
    )
    if campaign:
        sequence.campaign_name = campaign
    return sequence, ""


async def enqueue_sequence(
    backend, item, fields: list, values: dict, label: str = "", campaign: str = ""
) -> tuple:
    """Unpack the selected sequence and enqueue it directly.

    Returns:
        tuple: ``(message, error)``. Exactly one is non-empty. Nothing reaches
        the orchestrator while a parameter will not convert.
    """
    sequence, error = build_sequence(
        backend, item, fields, values, label=label, campaign=campaign
    )
    if error:
        return "", error
    name = sequence.sequence_name
    try:
        await backend.add_sequence(sequence)
    except Exception as exc:
        LOGGER.warning(f"operator could not enqueue sequence '{name}': {exc}")
        return "", f"{name} could not be enqueued: {exc}"
    return (
        f"enqueued {name} ({len(sequence.planned_experiments)} experiment(s))",
        "",
    )


#: Parameters the Bokeh operator renders as a dropdown of the PAL's configured
#: custom positions. Both read the same list.
CUSTOM_POSITION_PARAMS = ("solid_custom_position", "liquid_custom_position")


def custom_positions(world_cfg: dict) -> list:
    """Names of the PAL server's configured custom positions.

    Empty for a station with no PAL, which is most of them -- those params
    then render as plain text, exactly as they do in the Bokeh operator when
    its custom-item list is empty.
    """
    servers = (world_cfg or {}).get("servers") or {}
    for config in servers.values():
        if (config or {}).get("fast", "") != "pal_server":
            continue
        positions = ((config.get("params") or {}).get("positions") or {}).get(
            "custom", {}
        )
        return list(positions)
    return []


def options_map_for(world_cfg: dict) -> dict:
    """Dropdown options keyed by parameter name, for :func:`fields_for_item`."""
    positions = custom_positions(world_cfg)
    if not positions:
        return {}
    return {name: list(positions) for name in CUSTOM_POSITION_PARAMS}


class OperatorLibState(rx.State):
    """Library selection and the dynamic parameter form.

    Separate from :class:`OperatorQueueState` on purpose: Reflex re-renders
    every component bound to a state when any of its vars change, and a
    keystroke in a parameter field would otherwise re-push all four queue
    tables.

    Entered values live in ``_values``, keyed by ``(kind, item name)``, so
    switching tabs or items and coming back does not silently discard what was
    typed.
    """

    mode: str = "sequence"
    seq_names: list[str] = []
    exp_names: list[str] = []
    selected_sequence: str = ""
    selected_experiment: str = ""

    #: ``[name, kind, current value, help]`` per field. Flattened to strings
    #: because rx.foreach needs a concrete element type and cannot iterate
    #: heterogeneous dicts.
    param_rows: list[list[str]] = []
    #: Options for every ``select`` field. One list serves them all: the only
    #: dropdown params are the two custom positions, and both read the PAL's
    #: single list.
    position_options: list[str] = []

    doc: str = ""
    version_hint: str = ""
    sequence_label: str = ""
    campaign_name: str = ""
    status: str = ""
    error: str = ""

    #: Typed field descriptors and entered values, server-side only.
    _fields: list = []
    _values: dict = {}
    _items: dict = {}

    @rx.var
    def selected_name(self) -> str:
        """Name selected in the active tab."""
        return (
            self.selected_sequence
            if self.mode == "sequence"
            else self.selected_experiment
        )

    @rx.var
    def item_names(self) -> list[str]:
        """Selectable names for the active tab."""
        return self.seq_names if self.mode == "sequence" else self.exp_names

    def _world_cfg(self) -> dict:
        with _SETTINGS_LOCK:
            return _SETTINGS.get("world_cfg") or {}

    def _select(self, kind: str, name: str) -> None:
        """Rebuild the form for one library item."""
        item = item_by_name(self._items.get(kind, []), kind, name)
        if item is None:
            self._fields = []
            self.param_rows = []
            self.doc = ""
            self.version_hint = ""
            return
        world_cfg = self._world_cfg()
        self._fields = fields_for_item(item, options_map_for(world_cfg))
        entered = self._values.get((kind, name), {})
        self.param_rows = [
            [f["name"], f["kind"], entered.get(f["name"], f["default"]), f["help"]]
            for f in self._fields
        ]
        self.doc = item.get("doc", "")
        self.version_hint = version_text(item)

    @rx.event(background=True)
    async def load_libraries(self):
        """Introspect both libraries off the backend.

        Background because the first call imports every experiment and
        sequence module the config names, which on a station takes seconds.
        """
        async with self:
            token = self.router.session.client_token
            world_cfg = self._world_cfg()
        backend = session_backend(token)
        libraries = {
            kind: library_items(backend, kind, world_cfg)
            for kind in ("sequence", "experiment")
        }
        async with self:
            self._items = {kind: items for kind, (items, _) in libraries.items()}
            self.seq_names = libraries["sequence"][1]
            self.exp_names = libraries["experiment"][1]
            self.position_options = custom_positions(world_cfg)
            if self.seq_names and self.selected_sequence not in self.seq_names:
                self.selected_sequence = self.seq_names[0]
            if self.exp_names and self.selected_experiment not in self.exp_names:
                self.selected_experiment = self.exp_names[0]
            self._select(self.mode, self.selected_name)
            if not self.seq_names and not self.exp_names:
                self.error = "no sequence or experiment library is loaded"

    @rx.event
    def set_mode(self, mode: str):
        """Switch between the sequence and experiment tabs."""
        if mode not in LIBRARY_KINDS:
            return
        self.mode = mode
        self._select(mode, self.selected_name)

    @rx.event
    def select_item(self, name: str):
        """Choose a library item in the active tab."""
        if self.mode == "sequence":
            self.selected_sequence = name
        else:
            self.selected_experiment = name
        self._select(self.mode, name)

    @rx.event
    def set_param(self, name: str, value: str):
        """Record one edited parameter.

        Kept in ``_values`` as well as the rendered row so the entry survives
        switching items or tabs and switching back.
        """
        key = (self.mode, self.selected_name)
        entered = dict(self._values.get(key, {}))
        entered[name] = value
        self._values = {**self._values, key: entered}
        self.param_rows = [
            [row[0], row[1], value, row[3]] if row[0] == name else row
            for row in self.param_rows
        ]

    @rx.event
    def reset_params(self):
        """Drop every edit and return the form to the library defaults."""
        self._values = {
            k: v
            for k, v in self._values.items()
            if k != (self.mode, self.selected_name)
        }
        self._select(self.mode, self.selected_name)

    @rx.event(background=True)
    async def enqueue(self):
        """Enqueue the selected sequence with the entered parameters."""
        async with self:
            token = self.router.session.client_token
            kind, name = self.mode, self.selected_name
            item = item_by_name(self._items.get(kind, []), kind, name)
            fields = list(self._fields)
            values = dict(self._values.get((kind, name), {}))
            label, campaign = self.sequence_label, self.campaign_name
            self.status = ""
            self.error = ""
        if kind != "sequence":
            # Experiments reach the orchestrator inside a sequence; the plan
            # tab builds that, so enqueueing one directly is not offered.
            async with self:
                self.error = "select a sequence to enqueue"
            return
        message, error = await enqueue_sequence(
            session_backend(token), item, fields, values, label=label, campaign=campaign
        )
        async with self:
            self.status = message
            self.error = error


# -- plan buffer -------------------------------------------------------------

#: Columns of the plan table, matching the Bokeh operator's.
PLAN_COLS = ["sequence_name", "sequence_label", "num_experiments"]

#: How a buffered plan reaches the orchestrator.
PLAN_MODES = ("append", "split", "prepend")


def plan_rows(plan: list) -> list:
    """Render the buffered sequences as table rows."""
    return [
        [
            str(sequence.sequence_name or ""),
            str(sequence.sequence_label or ""),
            str(len(sequence.planned_experiments or [])),
        ]
        for sequence in plan or []
    ]


def plan_moved(plan: list, index: int, direction: str):
    """Plan buffer with one entry moved, or ``None`` when the move cannot happen.

    Returns a new list rather than mutating: the handler assigns it to a state
    var, and mutating the existing list in place would change what Reflex is
    holding without telling it.
    """
    target = moved_index(index, direction, len(plan or []))
    if target is None:
        return None
    moved = list(plan)
    moved[index], moved[target] = moved[target], moved[index]
    return moved


def plan_removed(plan: list, index: int):
    """Plan buffer without one entry, or ``None`` when the index is not in it."""
    if index < 0 or index >= len(plan or []):
        return None
    remaining = list(plan)
    remaining.pop(index)
    return remaining


async def dispatch_plan(backend, plan: list, mode: str) -> str:
    """Send the buffered plan to the orchestrator.

    ``prepend`` hands over the whole list in one call. Prepending one sequence
    at a time would reverse the buffer's order at the head of the queue.

    Returns:
        str: Empty on success, else a message naming the sequence that failed.
        A partial flush is the dangerous case -- some queued, some not -- so
        the message says where it stopped rather than that "something" failed.
    """
    if mode not in PLAN_MODES:
        LOGGER.warning(f"operator refused plan mode '{mode}'")
        return f"unknown plan mode '{mode}'"
    if not plan:
        return ""
    if backend is None:
        return "no orchestrator connection"
    if mode == "prepend":
        try:
            await backend.prepend_sequences(list(plan))
        except Exception as exc:
            LOGGER.warning(f"operator could not prepend the plan: {exc}")
            return f"the plan could not be prepended: {exc}"
        return ""
    method = backend.add_sequence if mode == "append" else backend.add_split_sequences
    for sequence in plan:
        try:
            await method(sequence)
        except Exception as exc:
            name = sequence.sequence_name
            LOGGER.warning(f"operator could not enqueue '{name}': {exc}")
            return f"stopped at {name}: {exc}"
    return ""


# -- history -----------------------------------------------------------------

#: Columns per history table, in the Bokeh operator's order.
HIST_COLS = {
    "action": [
        "action_endpoint",
        "action_status",
        "action_uuid",
        "experiment_name",
        "sequence_label",
        "start",
        "finish",
    ],
    "experiment": [
        "experiment_name",
        "experiment_uuid",
        "experiment_status",
        "sequence_label",
        "campaign_name",
        "start",
        "finish",
    ],
    "sequence": [
        "sequence_name",
        "sequence_uuid",
        "sequence_status",
        "sequence_label",
        "campaign_name",
        "start",
        "finish",
    ],
}

#: Per kind, the payload keys holding the start and finish timestamps.
_HIST_TIMES = {
    "action": ("action_timestamp", "action_finished_timestamp"),
    "experiment": ("experiment_timestamp", "experiment_finished_timestamp"),
    "sequence": ("sequence_timestamp", "sequence_finished_timestamp"),
}


def _last_of(value):
    """Status fields arrive as a list of transitions; the current one is last."""
    if isinstance(value, list):
        return value[-1] if value else ""
    return "" if value is None else value


def history_rows(histories: Optional[dict], kind: str) -> list:
    """Render one history table.

    Args:
        histories: ``get_histories`` payload -- ``kind -> [(uuid, payload)]``.
        kind: ``action``, ``experiment``, or ``sequence``.

    Returns:
        list[list[str]]: Most recent first, one cell per column. Every row
        carries every column even when the payload lacks the key: ragged rows
        are what made the Bokeh table refuse to render, and here they would
        silently shift cells under the wrong headers.
    """
    columns = HIST_COLS.get(kind)
    if columns is None:
        return []
    entries = ((histories or {}).get(kind)) or []
    start_key, finish_key = _HIST_TIMES[kind]
    rows = []
    for uuid, payload in sorted(entries, key=lambda x: x[0])[::-1]:
        payload = payload or {}
        derived = dict(payload)
        derived[f"{kind}_uuid"] = str(uuid)[-8:]
        derived["start"] = payload.get(start_key)
        derived["finish"] = payload.get(finish_key)
        if kind == "action":
            derived["action_endpoint"] = (
                f"{payload.get('action_server', '')}/{payload.get('action_name', '')}"
            )
        rows.append([str(_last_of(derived.get(col))) for col in columns])
    return rows


class OperatorPlanState(rx.State):
    """The client-side plan buffer and the history tables.

    The buffer is the one piece of operator state the orchestrator does not
    own: sequences are assembled and reordered here, and only reach the
    orchestrator when the operator flushes them. That is why these rows are
    edited locally, unlike the queue tables.
    """

    plan_view: list[list[str]] = []
    selected_row: int = -1
    status: str = ""
    error: str = ""

    action_history: list[list[str]] = []
    experiment_history: list[list[str]] = []
    sequence_history: list[list[str]] = []

    #: Buffered Sequence models. A backend var: these are pydantic models, not
    #: JSON, and the browser only ever needs `plan_view`.
    _plan: list = []

    @rx.var
    def plan_count(self) -> int:
        """How many sequences are buffered, for the flush button's label."""
        return len(self.plan_view)

    def _set_plan(self, plan: list) -> None:
        self._plan = plan
        self.plan_view = plan_rows(plan)
        if self.selected_row >= len(plan):
            self.selected_row = -1

    async def _add(self, prepend: bool):
        """Build a sequence from the library tab's selection and buffer it."""
        lib = await self.get_state(OperatorLibState)
        kind, name = lib.mode, lib.selected_name
        item = item_by_name(lib._items.get(kind, []), kind, name)
        fields = list(lib._fields)
        values = dict(lib._values.get((kind, name), {}))
        label, campaign = lib.sequence_label, lib.campaign_name
        if kind == "sequence":
            backend = session_backend(self.router.session.client_token)
            sequence, error = build_sequence(
                backend, item, fields, values, label=label, campaign=campaign
            )
        else:
            sequence, error = build_manual_sequence(
                item, fields, values, label=label, campaign=campaign
            )
        if error:
            self.error = error
            return
        self.error = ""
        plan = list(self._plan)
        plan.insert(0, sequence) if prepend else plan.append(sequence)
        self._set_plan(plan)
        self.status = f"buffered {sequence.sequence_name}"

    @rx.event
    async def append_selection(self):
        """Add the current selection to the end of the buffer."""
        await self._add(prepend=False)

    @rx.event
    async def prepend_selection(self):
        """Add the current selection to the front of the buffer."""
        await self._add(prepend=True)

    @rx.event
    def select_row(self, index: int):
        """Select one buffered row, or deselect it when clicked again."""
        self.selected_row = -1 if index == self.selected_row else index

    @rx.event
    def move_row(self, direction: str):
        """Move the selected row within the buffer.

        The selection follows the row it was on, so holding a button moves one
        sequence rather than walking the selection down the table.
        """
        target = moved_index(self.selected_row, direction, len(self._plan))
        moved = plan_moved(self._plan, self.selected_row, direction)
        if target is None or moved is None:
            return
        self._set_plan(moved)
        self.selected_row = target

    @rx.event
    def remove_row(self):
        """Drop the selected row from the buffer."""
        remaining = plan_removed(self._plan, self.selected_row)
        if remaining is None:
            return
        self._set_plan(remaining)
        self.selected_row = -1

    @rx.event
    def clear_plan(self):
        """Empty the buffer without sending anything."""
        self._set_plan([])
        self.status = ""

    @rx.event(background=True)
    async def flush(self, mode: str):
        """Send the buffer to the orchestrator.

        The buffer is emptied *before* the first await. A flush that cleared
        afterwards would let a second click dispatch the same sequences again
        while the first was still in flight -- the same reason the Bokeh
        operator clears synchronously and dispatches on the next tick.
        """
        async with self:
            plan = list(self._plan)
            token = self.router.session.client_token
            self._set_plan([])
            self.error = ""
            self.status = f"sending {len(plan)} sequence(s)..." if plan else ""
        error = await dispatch_plan(session_backend(token), plan, mode)
        async with self:
            self.error = error
            self.status = "" if error else f"sent {len(plan)} sequence(s)"

    @rx.event(background=True)
    async def refresh_history(self):
        """Reload all three history tables."""
        async with self:
            token = self.router.session.client_token
        backend = session_backend(token)
        if backend is None:
            return
        try:
            histories = await backend.get_histories()
        except Exception as exc:
            LOGGER.warning(f"operator history refresh failed: {exc}")
            async with self:
                self.error = f"history unavailable: {exc}"
            return
        async with self:
            self.action_history = history_rows(histories, "action")
            self.experiment_history = history_rows(histories, "experiment")
            self.sequence_history = history_rows(histories, "sequence")


# -- plate map ---------------------------------------------------------------

#: Composition fraction keys on a platemap entry, in display order.
FRACTION_KEYS = ("A", "B", "C", "D", "E", "F", "G", "H")

#: Plate APIs the operator knows how to build, by config value.
PLATE_APIS = ("HTEPlateAPI",)

_PLATE_API_CACHE: dict = {}


def plate_api_for(server_cfg: dict):
    """Build the configured plate API, or ``None`` when there is none.

    Opt-in, as in the Bokeh operator: most stations have no plate API, and an
    unknown name is ignored rather than imported, so a typo cannot pull in
    something arbitrary.
    """
    name = ((server_cfg or {}).get("params") or {}).get("plate_api")
    if name not in PLATE_APIS:
        if name:
            LOGGER.warning(f"operator ignoring unknown plate_api '{name}'")
        return None
    cached = _PLATE_API_CACHE.get(name)
    if cached is not None:
        return cached
    try:
        from helao.helpers.plate_api import HTEPlateAPI

        cached = HTEPlateAPI()
    except Exception as exc:
        LOGGER.warning(f"operator could not build plate API '{name}': {exc}")
        return None
    _PLATE_API_CACHE[name] = cached
    return cached


def _as_number(value):
    """Read one coordinate, or ``None`` when it is not a number."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def platemap_points(pmdata: Optional[list]) -> tuple:
    """Split a platemap into plottable coordinates and sample numbers.

    A row whose coordinates will not convert is dropped whole. Handing a
    non-numeric value to ``plots`` raises from inside the render and takes the
    entire chart down, and dropping only one of the pair would leave x and y
    at different lengths, which ``scatter_map`` rejects.

    Returns:
        tuple: ``(xs, ys, sample_nos)``, all the same length. Sample numbers
        are 1-based, matching the plate's own numbering.
    """
    xs, ys, samples = [], [], []
    for index, entry in enumerate(pmdata or []):
        x = _as_number((entry or {}).get("x"))
        y = _as_number((entry or {}).get("y"))
        if x is None or y is None:
            continue
        xs.append(x)
        ys.append(y)
        samples.append(index + 1)
    return xs, ys, samples


def nearest_sample(pmdata: Optional[list], x: float, y: float):
    """Sample number nearest a clicked point, or ``None`` on an empty map.

    Matched against the plottable rows only: a click lands on the rendered
    map, which does not contain the rows that were dropped, so matching
    against them could return a sample the operator cannot see.
    """
    xs, ys, samples = platemap_points(pmdata)
    if not xs:
        return None
    best = min(range(len(xs)), key=lambda i: (xs[i] - x) ** 2 + (ys[i] - y) ** 2)
    return samples[best]


def composition_text(entry: Optional[dict]) -> str:
    """Composition fractions of one platemap entry, as one line.

    A dash when there are none: an empty readout reads as a failure to load
    rather than a plate with no composition.
    """
    entry = entry or {}
    parts = [
        f"{key}_{entry[key]}" for key in FRACTION_KEYS if entry.get(key) is not None
    ]
    return " ".join(parts) if parts else "-"


def sample_summary(pmdata: Optional[list], sample_no: int) -> dict:
    """Code and composition for one sample number.

    Args:
        pmdata: The platemap.
        sample_no: 1-based sample number. ``0`` is rejected rather than
            treated as an index, which would silently return the last sample
            on the plate.

    Returns:
        dict: ``sample_no``, ``code``, ``composition``, and ``error``.
    """
    blank = {"sample_no": str(sample_no), "code": "", "composition": ""}
    entries = pmdata or []
    if sample_no < 1 or sample_no > len(entries):
        return {**blank, "error": f"sample {sample_no} is not on this plate"}
    entry = entries[sample_no - 1] or {}
    return {
        "sample_no": str(sample_no),
        "code": "" if entry.get("code") is None else str(entry["code"]),
        "composition": composition_text(entry),
        "error": "",
    }


class OperatorPlateState(rx.State):
    """The plate map: a scatter of a plate's samples, selectable by click.

    Opt-in. Without ``plate_api`` in the server params there is no plate data
    to draw, and the tab says so rather than rendering an empty chart that
    looks broken -- the same gate the Bokeh operator applies, which its suite
    covers in ``test_plate_api_disabled_by_default``.
    """

    plate_id: str = ""
    sample_no: str = ""
    code: str = ""
    composition: str = ""
    enabled: bool = False
    status: str = ""
    error: str = ""

    chart_spec: dict = {}
    chart_url: str = ""
    chart_layout: str = ""
    version: int = 0

    #: The loaded platemap. A backend var: it is a list of dicts per sample and
    #: the browser needs only the rendered points.
    _pmdata: list = []

    def panel_key(self) -> str:
        """Session-scoped buffer-store key.

        The store holds one frame per key while ``version`` is per-session
        state, so a shared key would 404 two tabs into frozen charts.
        """
        return f"plate-{self.router.session.client_token}"

    def _plate_api(self):
        with _SETTINGS_LOCK:
            world_cfg = _SETTINGS.get("world_cfg") or {}
            server_key = _SETTINGS.get("server_key", "")
        server_cfg = (world_cfg.get("servers") or {}).get(server_key) or {}
        return plate_api_for(server_cfg)

    @rx.event
    def on_mount(self):
        """Report whether this station has a plate API at all."""
        self.enabled = self._plate_api() is not None
        if not self.enabled:
            self.status = "no plate API is configured for this station"

    def _redraw(self) -> None:
        xs, ys, samples = platemap_points(self._pmdata)
        self.version += 1
        payload = plots.scatter_map(
            xs,
            ys,
            values=samples or None,
            x_label="x (mm)",
            y_label="y (mm)",
            panel_id=self.panel_key(),
            version=self.version,
        )
        self.chart_spec = payload.spec
        self.chart_url = payload.buffer_url
        self.chart_layout = payload.layout

    @rx.event(background=True)
    async def load_plate(self):
        """Fetch and draw the platemap for the entered plate id."""
        async with self:
            api = self._plate_api()
            raw = self.plate_id.strip()
            self.error = ""
        if api is None:
            async with self:
                self.error = "no plate API is configured for this station"
            return
        try:
            plateid = int(raw)
        except ValueError:
            async with self:
                self.error = f"'{raw}' is not a plate id"
            return
        try:
            pmdata = api.get_platemap_plateid(plateid)
        except Exception as exc:
            LOGGER.warning(f"operator could not load plate {plateid}: {exc}")
            async with self:
                self.error = f"plate {plateid} could not be loaded: {exc}"
            return
        async with self:
            self._pmdata = list(pmdata or [])
            if not self._pmdata:
                self.status = f"plate {plateid} has no platemap"
                return
            self.status = f"plate {plateid}: {len(self._pmdata)} samples"
            self._redraw()

    @rx.event
    def on_select(self, payload: dict):
        """Snap to the sample nearest a click on the map."""
        x = _as_number((payload or {}).get("x"))
        y = _as_number((payload or {}).get("y"))
        if x is None or y is None:
            return
        sample = nearest_sample(self._pmdata, x, y)
        if sample is None:
            return
        self.set_sample(str(sample))

    @rx.event
    def set_sample(self, value: str):
        """Set the sample number and refresh its readouts."""
        self.sample_no = value
        try:
            sample = int(value)
        except (TypeError, ValueError):
            self.code = ""
            self.composition = ""
            return
        summary = sample_summary(self._pmdata, sample)
        self.code = summary["code"]
        self.composition = summary["composition"]
        self.error = summary["error"]
