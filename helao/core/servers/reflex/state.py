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
"""

__all__ = [
    "VisPanelState",
    "LiveVisState",
    "ActionVisState",
    "make_panel_state",
]

import asyncio

import reflex as rx

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


class VisPanelState(rx.State):
    """Base state for a visualizer panel bound to one ingest target.

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

    # Class-level defaults readable without instantiating a State. Reflex
    # manages the vars above per session; these mirror the bound values so
    # app-build code and tests can introspect them.
    server_key_default: str = ""
    ws_path_default: str = "ws_live"

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
        return registry.get(self.server_key or self.server_key_default, self.ws_path)

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
            if self.running:
                return
            self.running = True
        try:
            while True:
                async with self:
                    if not self.running:
                        return
                    ingest = self.ingest()
                    if ingest is None:
                        self.connection = "unavailable"
                        self.error = (
                            f"no ingest for '{self.server_key or self.server_key_default}' "
                            f"({self.ws_path}); is it declared in the config?"
                        )
                    else:
                        self.connection = ingest.status.state
                        self.error = ingest.status.error or ""
                        try:
                            self.pull(ingest)
                        except Exception as exc:
                            self.error = f"{type(exc).__name__}: {exc}"
                            LOGGER.warning(
                                f"reflex panel pull failed for "
                                f"{self.server_key_default}: {exc}"
                            )
                    interval = self.update_rate
                await asyncio.sleep(interval)
        finally:
            async with self:
                self.running = False

    @rx.event
    def stop_loop(self):
        """Ask the render loop to exit on its next tick."""
        self.running = False


class LiveVisState(VisPanelState):
    """Panel state for continuous sensor telemetry (``ws_live``)."""

    ws_path: str = "ws_live"
    ws_path_default: str = "ws_live"
    update_rate: float = 0.5


class ActionVisState(VisPanelState):
    """Panel state for per-action measurement packages (``ws_data``)."""

    ws_path: str = "ws_data"
    ws_path_default: str = "ws_data"
    update_rate: float = 0.25


_STATE_CACHE: dict = {}


def make_panel_state(module_name: str, server_key: str, base: type, ws_path: str):
    """Mint (or return the cached) State subclass bound to one ingest target.

    Reflex rejects duplicate State class names, so results are cached by
    ``(module_name, server_key, base)`` and a re-render reuses the same class.

    Args:
        module_name: Panel module short name, e.g. ``"wssim_panel"``.
        server_key: Action server this panel reads.
        base: The :class:`VisPanelState` subclass to extend.
        ws_path: ``ws_live`` or ``ws_data``.

    Returns:
        type: A ``base`` subclass with ``server_key`` and ``ws_path`` bound.
    """
    cache_key = (module_name, server_key, base.__name__)
    if cache_key in _STATE_CACHE:
        return _STATE_CACHE[cache_key]
    safe = "".join(c if c.isalnum() else "_" for c in f"{module_name}_{server_key}")
    cls = type(
        f"{safe}_State",
        (base,),
        {
            # Reflex's ``StateBase`` metaclass resolves field annotations via
            # ``sys.modules[namespace["__module__"]]``, so the key must exist
            # even though this class has no new annotated fields of its own.
            # Pointing it at this module (rather than leaving it unset) means
            # any future string/forward-ref annotation resolves against real
            # globals instead of failing a lookup against a made-up name.
            "__module__": __name__,
            "server_key": server_key,
            "ws_path": ws_path,
            "server_key_default": server_key,
            "ws_path_default": ws_path,
            "__doc__": (
                f"Generated panel state binding '{module_name}' to server "
                f"'{server_key}' on '{ws_path}'."
            ),
        },
    )
    _STATE_CACHE[cache_key] = cls
    return cls
