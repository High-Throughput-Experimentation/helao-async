"""Reflex state bases for HELAO visualizer panels.

These are the Reflex analogues of
:class:`~helao.core.servers.vis_subscriber.LiveVisualizer` and
:class:`~helao.core.servers.vis_subscriber.ActionVisualizer`. The base owns
render cadence, connection status, and error capture; a panel subclass supplies
only :meth:`VisPanelState.pull`, which reads the shared ingest buffer and
assigns the panel's own state vars.

Reflex requires ``State`` subclasses to be real classes, so a panel cannot be
bound to a runtime ``server_key`` by instantiation. :func:`make_panel_state`
mints one cached subclass per ``(module_name, server_key)`` instead.

**Everything here is a Reflex mixin, and that is load-bearing.** A var declared
on a real ``rx.State`` is owned by that class and *shared* by every substate
below it: a subclass that re-declares it does not shadow it, and reads route to
the ancestor's single stored value. Written as plain inheritance, this module
shipped two bugs at once -- ``server_key`` bound by :func:`make_panel_state`
read back as ``""`` at runtime (so no panel could find its ingest), and two
panels on one page shared one ``connection``, ``window_points``, ``chart_spec``.
Declaring these classes with ``mixin=True`` makes Reflex *copy* the vars and
event handlers into each generated leaf state, which is the per-panel isolation
the design assumes.
"""

__all__ = [
    "VisPanelState",
    "LiveVisState",
    "ActionVisState",
    "make_panel_state",
    "apply_tick",
    "loop_superseded",
    "may_clear_running",
]

import asyncio
import sys

import reflex as rx

from helao.core.servers.reflex import plots
from helao.core.servers.reflex.ingest import get_registry
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Window bounds carried over from ``VisSubscriber.callback_input_max_points``
#: so operators see the same clamping they are used to.
MIN_WINDOW_POINTS = 2
MAX_WINDOW_POINTS = 10000
DEFAULT_WINDOW_POINTS = 500
MIN_UPDATE_RATE = 0.01
DEFAULT_UPDATE_RATE = 0.5


def loop_superseded(current_generation: int, token: int) -> bool:
    """Whether a loop holding ``token`` has been replaced and must exit.

    Framework-free so the race fix is testable: ``rx.State`` cannot be built
    outside app machinery, and the previous version of this logic -- a single
    shared ``running`` boolean -- shipped a real double-loop bug that no test
    could have caught.

    Args:
        current_generation: The state's current ``loop_generation``.
        token: The generation this loop captured when it started.

    Returns:
        bool: ``True`` when a newer loop (or a stop) has bumped the generation.
    """
    return current_generation != token


def may_clear_running(current_generation: int, token: int) -> bool:
    """Whether an exiting loop owns the ``running`` flag.

    A superseded loop must not clear the flag on its way out; doing so would
    report the live loop as stopped.

    Args:
        current_generation: The state's current ``loop_generation``.
        token: The generation of the loop that is exiting.

    Returns:
        bool: ``True`` only when the exiting loop is still the current one.
    """
    return current_generation == token


def apply_tick(target, ingest, *, server_key: str, ws_path: str) -> None:
    """Apply one poll of ``ingest`` onto ``target``.

    Lifted out of :meth:`VisPanelState.render_loop` so the part that can be
    wrong is reachable without Reflex's app machinery: ``target`` is anything
    with ``connection`` and ``error`` attributes and a ``pull`` method, so
    tests drive it with a stub. The loop is then only locking and cadence.

    A failing ``pull`` is caught here rather than by the caller, so one bad
    tick marks the panel and the loop keeps its cadence instead of dying.

    Args:
        target: The panel state (or a stub) being updated.
        ingest: The panel's :class:`WsIngest`, or ``None`` when unavailable.
        server_key: Server this panel reads, for the message.
        ws_path: ``ws_live`` or ``ws_data``, for the message.
    """
    if ingest is None:
        target.connection = "unavailable"
        target.error = (
            f"no ingest for '{server_key}' ({ws_path}); "
            "is it declared in the config?"
        )
        return
    target.connection = ingest.status.state
    target.error = ingest.status.error or ""
    try:
        target.pull(ingest)
    except Exception as exc:
        target.error = f"{type(exc).__name__}: {exc}"
        LOGGER.warning(f"reflex panel pull failed for {server_key}: {exc}")


class VisPanelState(rx.State, mixin=True):
    """Base state for a visualizer panel bound to one ingest target.

    A mixin, not a state: see this module's docstring. Panels subclass it with
    ``mixin=True`` too, and :func:`make_panel_state` turns the chain into a
    real state exactly once, at the leaf.

    Attributes:
        server_key: Action server this panel reads.
        ws_path: ``ws_live`` or ``ws_data``.
        window_points: Trailing rows pulled from the ring buffer per render.
        update_rate: Seconds between renders.
        connection: Mirror of the ingest status: ``connecting``, ``live``,
            ``reconnecting``, or ``unavailable``.
        error: Most recent error string, empty when healthy.
        running: Whether the render loop is active.
    """

    server_key: str = ""
    ws_path: str = "ws_live"
    window_points: int = DEFAULT_WINDOW_POINTS
    update_rate: float = DEFAULT_UPDATE_RATE
    connection: str = "connecting"
    error: str = ""
    running: bool = False
    #: Bumped on every loop start and every stop. A loop keeps its own token
    #: and exits as soon as the two diverge. A single shared boolean cannot
    #: do this: it is asked both "is a loop active" and "should THIS
    #: invocation continue", and those answers differ during a
    #: stop-then-immediate-restart.
    loop_generation: int = 0

    @staticmethod
    def clamp_window_points(value, fallback=None) -> int:
        """Parse and clamp a window size the way the Bokeh input did.

        Args:
            value: Raw text from the input widget.
            fallback: Value to use when ``value`` will not parse. ``None``
                means :data:`DEFAULT_WINDOW_POINTS`.

        Returns:
            An int in ``[MIN_WINDOW_POINTS, MAX_WINDOW_POINTS]``.
        """
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = DEFAULT_WINDOW_POINTS if fallback is None else int(fallback)
        return max(MIN_WINDOW_POINTS, min(MAX_WINDOW_POINTS, parsed))

    @staticmethod
    def parse_update_rate(value) -> float:
        """Parse a render interval, defaulting and flooring like the Bokeh input.

        Args:
            value: Raw text from the input widget.

        Returns:
            A float of at least :data:`MIN_UPDATE_RATE`.
        """
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = DEFAULT_UPDATE_RATE
        return max(MIN_UPDATE_RATE, parsed)

    @rx.event
    def on_window_points(self, value: str):
        """Handle the window-size input."""
        self.window_points = self.clamp_window_points(value, self.window_points)

    @rx.event
    def on_update_rate(self, value: str):
        """Handle the render-interval input."""
        self.update_rate = self.parse_update_rate(value)

    def ingest(self):
        """Return this panel's :class:`WsIngest`, or ``None`` if unavailable."""
        registry = get_registry()
        if registry is None:
            return None
        return registry.get(self.server_key, self.ws_path)

    def panel_key(self) -> str:
        """Return this panel's buffer-store key for the current session.

        ``panel_id`` must be scoped per browser session, not per server: the
        buffer store keeps one frame per key while ``version`` is per-session
        Reflex state, so two sessions sharing a key would 404 each other into a
        permanently frozen chart. Panel modules override this to fold in
        ``self.router.session.client_token``; this base implementation is only
        a fallback so :meth:`stop_loop` always has something to drop.
        """
        return f"{self.server_key}-{self.router.session.client_token}"

    def pull(self, ingest) -> None:
        """Copy data from ``ingest`` into this panel's state vars.

        Args:
            ingest: The panel's :class:`WsIngest`.

        Raises:
            NotImplementedError: Panels must implement this.
        """
        raise NotImplementedError

    @rx.event(background=True)
    async def render_loop(self):
        """Poll the ingest buffer at ``update_rate`` until the session ends.

        Ingest runs independently at WebSocket speed; this loop only samples it.
        That decoupling is the point -- a fast stream cannot drag the render
        cadence with it the way ``VisSubscriber.IOloop_data`` does.
        """
        async with self:
            self.loop_generation += 1
            token = self.loop_generation
            self.running = True
        try:
            while True:
                async with self:
                    # Not `if not self.running`: `async with self` refetches
                    # state, so a loop that slept through a stop-then-restart
                    # would see the *new* loop's True and both would run.
                    if loop_superseded(self.loop_generation, token):
                        return
                    ingest = self.ingest()
                    apply_tick(
                        self,
                        ingest,
                        server_key=self.server_key,
                        ws_path=self.ws_path,
                    )
                    interval = self.update_rate
                await asyncio.sleep(interval)
        finally:
            async with self:
                # Only the current loop may clear the flag; a superseded one
                # exiting must not report the live loop as stopped.
                if may_clear_running(self.loop_generation, token):
                    self.running = False

    @rx.event
    def stop_loop(self):
        """Ask the render loop to exit on its next tick, and free its buffer.

        Releases this panel's entry from :data:`plots.STORE` through
        :meth:`~helao.core.servers.reflex.xy_component.BufferStore.drop`, so a
        closed session's frame does not linger under a key nothing will ever
        refetch.
        """
        self.loop_generation += 1
        self.running = False
        plots.STORE.drop(self.panel_key())


class LiveVisState(VisPanelState, mixin=True):
    """Panel state for continuous sensor telemetry (``ws_live``)."""

    ws_path: str = "ws_live"
    update_rate: float = 0.5


class ActionVisState(VisPanelState, mixin=True):
    """Panel state for per-action measurement packages (``ws_data``)."""

    ws_path: str = "ws_data"
    update_rate: float = 0.25


_STATE_CACHE: dict = {}

#: Generated class-name occupancy, so two distinct cache keys cannot mint two
#: Reflex substates under the same name.
_NAME_SEQ: dict = {}


def make_panel_state(module_name: str, server_key: str, base: type, ws_path: str):
    """Mint (or return the cached) State class bound to one ingest target.

    ``base`` must be a Reflex *mixin* (``class ...(LiveVisState, mixin=True)``).
    This is the one place the mixin chain becomes a real ``rx.State``, and it
    has to stay that way: Reflex vars are owned by the class that declares them
    and shared by every substate beneath it, so a panel whose vars came from a
    concrete ancestor would read that ancestor's single copy -- ``server_key``
    would come back ``""`` and every panel on the page would share one
    ``chart_spec``. Mixin vars are copied into each leaf instead.

    Reflex rejects duplicate State class names, so results are cached by
    ``(module_name, server_key, base)`` and a re-render reuses the same class.

    Args:
        module_name: Panel module short name, e.g. ``"wssim_panel"``.
        server_key: Action server this panel reads.
        base: The :class:`VisPanelState` mixin subclass to build from.
        ws_path: ``ws_live`` or ``ws_data``.

    Returns:
        type: An ``rx.State`` subclass with ``server_key`` and ``ws_path`` bound.

    Raises:
        TypeError: If ``base`` is a concrete state rather than a mixin, which
            would silently produce shared vars.
    """
    if not getattr(base, "_mixin", False):
        raise TypeError(
            f"panel state base '{base.__name__}' must be declared with "
            "mixin=True; a concrete rx.State base makes every panel share one "
            "copy of each var, so server_key reads back empty."
        )
    # Keyed on the base class itself, not its __name__: two panel modules can
    # each define a same-named subclass, and a name collision would silently
    # hand one panel another's state class.
    cache_key = (module_name, server_key, base)
    if cache_key in _STATE_CACHE:
        return _STATE_CACHE[cache_key]
    safe = "".join(c if c.isalnum() else "_" for c in f"{module_name}_{server_key}")
    # Every generated state is a direct substate of rx.State, and Reflex
    # rejects two substates sharing a name ("Shadowing substate classes is not
    # allowed") -- a hard error at class creation, not a subtle one. Distinct
    # cache keys can still reduce to the same safe name (same module and server
    # key, different base), so uniqueness is enforced here rather than assumed.
    _NAME_SEQ[safe] = _NAME_SEQ.get(safe, 0) + 1
    if _NAME_SEQ[safe] > 1:
        safe = f"{safe}_{_NAME_SEQ[safe]}"
    cls = type(
        f"{safe}_State",
        # rx.State last: `base` is a mixin, so this is where the chain first
        # becomes a real state and where every mixin var is materialized.
        (base, rx.State),
        {
            # Reflex's ``StateBase`` metaclass resolves field annotations via
            # ``sys.modules[namespace["__module__"]]``, so the key must exist
            # even though this class has no new annotated fields of its own.
            # Pointing it at this module (rather than leaving it unset) means
            # any future string/forward-ref annotation resolves against real
            # globals instead of failing a lookup against a made-up name.
            "__module__": __name__,
            # Plain overrides of mixin var defaults. This works only because
            # the vars land on *this* class; against a concrete base they would
            # be inherited vars and the assignment would be ignored at runtime.
            "server_key": server_key,
            "ws_path": ws_path,
            "__doc__": (
                f"Generated panel state binding '{module_name}' to server "
                f"'{server_key}' on '{ws_path}'."
            ),
        },
    )
    # Publish the class as a module attribute under its own name. It is built
    # by type() and claims this module, so without this pickle cannot find it:
    # Reflex serializes state for persistence and logged a wall of
    #   StateSerializationError: ... due to unpicklable object.
    #   This state will not be persisted.
    # per tick, one per panel. Harmless with the in-memory state manager, fatal
    # to any disk- or Redis-backed one -- and the noise buries real errors.
    setattr(sys.modules[__name__], cls.__name__, cls)
    _STATE_CACHE[cache_key] = cls
    return cls
