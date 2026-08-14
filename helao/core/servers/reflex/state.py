"""Reflex state bases for HELAO visualizer panels.

These are the Reflex analogues of
:class:`~helao.ui.bokeh.vis_subscriber.LiveVisualizer` and
:class:`~helao.ui.bokeh.vis_subscriber.ActionVisualizer`. The base owns
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
    "assign",
]

import sys

import reflex as rx

from helao.core.servers.reflex import plots
from helao.core.servers.reflex.ingest import get_registry
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Window bounds. The minimum is carried over from
#: ``VisSubscriber.callback_input_max_points``; the maximum is no longer the
#: Bokeh visualizer's 10000 but the ring buffer's own capacity, because xy
#: reduces a window to roughly pixel resolution before it is published --
#: 1e6 points ship as ~3200, about 25 KB, in ~1 ms -- so the payload is bounded
#: by the chart's width rather than by the point count.
MIN_WINDOW_POINTS = 2
MAX_WINDOW_POINTS = 1_000_000
DEFAULT_WINDOW_POINTS = 1_000_000
MIN_UPDATE_RATE = 0.01
#: 60 Hz. What this costs is set by the window, not the rate: the reduction is
#: cheap but the numpy work ahead of it is not, and it runs per chart per tick.
#: Measured, one chart, one tick: 2.2 ms at a 500-point window, 3.0 ms at
#: 100k, 18.1 ms at 1e6 -- against the 16.7 ms a 60 Hz frame allows. A page of
#: six charts at a full window therefore settles near 9 Hz rather than 60. That
#: is a ceiling, not a fault: `_tick` drops a tick whose predecessor is still
#: rendering rather than queueing it, so the panel runs as fast as the backend
#: can and no faster.
DEFAULT_UPDATE_RATE = 1 / 60

#: Continuous sensor telemetry renders at 10 Hz, not 60. `ws_live` panels carry
#: several figures each and their sensors change on a human timescale, so the
#: extra 50 frames a second buy nothing and cost real work -- each tick rebuilds
#: every figure and publishes a frame per chart. A deliberate override of
#: :data:`DEFAULT_UPDATE_RATE`, which stays at 60 Hz for the per-action
#: measurement panels where a fast trace is the point.
DEFAULT_LIVE_UPDATE_RATE = 0.1


#: Sentinel so a first assignment of a falsy value is not mistaken for a no-op.
_MISSING = object()


def assign(target, name: str, value) -> bool:
    """Set ``target.name`` only when the value actually differs.

    Reflex marks a var dirty on **assignment**, not on change, and a dirty var
    is a delta pushed to the browser. Panels tick several times a second, so
    unconditional writes meant every panel published a delta every tick with
    nothing new in it. Charts absorbed that; a panel built from
    ``rx.data_table`` rebuilt all of its tables each time, which read at the
    bench as continuous flashing -- and as the panels below it bouncing, since
    a rebuilt table changes height. It also spent the browser's main thread on
    redraws that the live charts needed.

    Returns:
        bool: ``True`` if the value changed and was written.
    """
    if getattr(target, name, _MISSING) == value:
        return False
    setattr(target, name, value)
    return True


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
        assign(target, "connection", "unavailable")
        assign(
            target,
            "error",
            f"no ingest for '{server_key}' ({ws_path}); "
            "is it declared in the config?",
        )
        return
    assign(target, "connection", ingest.status.state)
    assign(target, "error", ingest.status.error or "")

    # Nothing new on the wire means nothing new to draw. Without this every
    # panel rebuilt and republished its whole payload on every tick -- a fresh
    # buffer URL, a fresh spec, a state delta -- for data identical to the
    # frame already on screen. On a page of ten panels that is the browser's
    # main thread spent on redraws the live charts needed, and it is why a
    # running trace could crawl while an idle table flashed beside it.
    seen = getattr(ingest.status, "message_count", None)
    if (
        seen is not None
        and seen == getattr(target, "_last_seen", None)
        and not getattr(target, "_force_pull", False)
    ):
        return

    try:
        target.pull(ingest)
    except Exception as exc:
        assign(target, "error", f"{type(exc).__name__}: {exc}")
        LOGGER.warning(f"reflex panel pull failed for {server_key}: {exc}")
    # Recorded after the pull, so a failed one is retried on the next tick
    # rather than being treated as done.
    else:
        if hasattr(target, "_last_seen"):
            target._last_seen = seen
        if getattr(target, "_force_pull", False):
            target._force_pull = False


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
    """

    server_key: str = ""
    ws_path: str = "ws_live"
    window_points: int = DEFAULT_WINDOW_POINTS
    update_rate: float = DEFAULT_UPDATE_RATE
    connection: str = "connecting"
    error: str = ""
    #: True while a tick is in flight, so a tick landing on a slow render is
    #: dropped rather than interleaved with it.
    #:
    #: Backend-only (leading underscore), and it must stay that way. As a
    #: normal var it flipped True then False on *every* tick, so every panel
    #: pushed a state delta to the browser at its render cadence whether or not
    #: anything had changed. A chart panel absorbs that invisibly; a panel made
    #: of ``rx.data_table`` rebuilds its tables on any delta, which reads as
    #: continuous flashing with no action running. Nothing renders this, so it
    #: has no business crossing the wire.
    _running: bool = False
    #: Ingest message count at the last completed pull, so a tick with nothing
    #: new on the wire costs nothing. Backend-only, like ``_running``.
    _last_seen: int = -1
    #: Set by anything that changes what a render should look like without new
    #: data arriving -- a new window size, a different axis. Without it those
    #: controls would appear dead on an idle panel, since the skip above would
    #: keep the stale frame until the next packet.
    _force_pull: bool = False

    def request_pull(self) -> None:
        """Force the next tick to re-render even with no new data."""
        self._force_pull = True

    #: Render cadence in milliseconds, for the page's ticking component. Kept
    #: beside `update_rate` rather than computed, because the component binds
    #: it as a Var and must see the change when the input is edited.
    tick_ms: int = int(DEFAULT_UPDATE_RATE * 1000)

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
        self.request_pull()

    @rx.event
    def on_update_rate(self, value: str):
        """Handle the render-interval input."""
        self.update_rate = self.parse_update_rate(value)
        self.tick_ms = int(self.update_rate * 1000)

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

    async def _tick(self):
        """Sample the ingest buffer once."""
        async with self:
            if self._running:
                # A tick landing while the previous render is still in flight
                # is dropped, not queued: a slow pull would otherwise stack
                # renders that interleave their writes.
                return
            self._running = True
        try:
            async with self:
                apply_tick(
                    self,
                    self.ingest(),
                    server_key=self.server_key,
                    ws_path=self.ws_path,
                )
        finally:
            async with self:
                self._running = False

    @rx.event(background=True)
    async def render_tick(self, _tick: str = ""):
        """Sample the ingest buffer once, driven by the page's interval.

        Ingest runs independently at WebSocket speed; this only samples it.
        That decoupling is the point -- a fast stream cannot drag the render
        cadence with it the way ``VisSubscriber.IOloop_data`` does.

        The cadence comes from a component in the page, **not** from a
        server-side loop. A ``while True`` in a background event outlives the
        browser tab: ``on_unmount`` fires on in-app navigation but never on a
        closed tab, so every abandoned tab left one loop per panel sampling
        forever and pushing deltas to a client that had gone.

        Args:
            _tick: The interval component's value. Unused; present because
                ``on_change`` passes one.
        """
        await self._tick()

    @rx.event(background=True)
    async def render_loop(self):
        """Prime the panel on mount, and set the tick cadence.

        Named for the loop it replaces: panel modules -- including ones in
        deployments outside this repo -- bind ``on_mount=state_cls.render_loop``,
        and they keep working unchanged. It now renders one frame; the page's
        interval component drives every frame after it.
        """
        async with self:
            # Set here rather than as a class default so a subclass that
            # overrides `update_rate` (LiveVisState does) cannot leave the two
            # disagreeing.
            self.tick_ms = int(self.update_rate * 1000)
        await self._tick()

    @rx.event
    def stop_loop(self):
        """Free this panel's buffer.

        Releases this panel's entry from :data:`plots.STORE` through
        :meth:`~helao.core.servers.reflex.xy_component.BufferStore.drop`, so a
        closed session's frame does not linger under a key nothing will ever
        refetch. The tick itself stops with the component that drives it.
        """
        self._running = False
        plots.STORE.drop(self.panel_key())


class LiveVisState(VisPanelState, mixin=True):
    """Panel state for continuous sensor telemetry (``ws_live``).

    Renders at :data:`DEFAULT_LIVE_UPDATE_RATE`. This is the one deliberate
    override of the module default, named rather than hardcoded -- the 0.5 s and
    0.25 s these classes used to carry were stale literals that silently
    shadowed the default, so raising it changed nothing for any real panel.
    """

    ws_path: str = "ws_live"
    update_rate: float = DEFAULT_LIVE_UPDATE_RATE


class ActionVisState(VisPanelState, mixin=True):
    """Panel state for per-action measurement packages (``ws_data``)."""

    ws_path: str = "ws_data"


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
