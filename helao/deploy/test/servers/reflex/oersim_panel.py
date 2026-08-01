"""Reflex panel for the OER simulator's per-action data stream.

Reflex port of ``servers/visualizer/oersim_vis.py``. Subscribes to ``ws_data``
and renders the action-scoped measurement traces.
"""

__all__ = ["WS_PATH", "STATE_BASE", "build", "extract", "panel_id"]

import numpy as np
import reflex as rx

from helao.core.servers.reflex import plots
from helao.core.servers.reflex.state import ActionVisState

WS_PATH = "ws_data"

#: The x axis is elapsed seconds from the data packet, not a wall-clock epoch:
#: ws_data packets carry no epoch column, so looking for one would leave x empty
#: and plot nothing. Matches the Bokeh original, which plots t_s vs erhe_v.
X_COLUMN = "t_s"


def panel_id(server_key: str, session_token: str) -> str:
    """Buffer-store identity for this panel in one browser session.

    Scoped per session: the store holds one frame per key while the version
    counter is per-session state, so a shared key lets two tabs 404 each other
    into a frozen chart.
    """
    return f"oersim-{server_key}-{session_token}"


def extract(ingest, window: int) -> dict:
    """Read the trailing window from the ring buffer.

    Args:
        ingest: The panel's :class:`WsIngest`.
        window: Number of trailing rows.

    Returns:
        dict: ``{"x": np.ndarray, "series": {name: np.ndarray},
        "action_uuid": str}``.
    """
    snap = ingest.buffer.snapshot(window)
    latest = ingest.rows.latest() or {}
    return {
        "x": snap.get(X_COLUMN, np.empty(0)),
        "series": {k: v for k, v in snap.items() if k != X_COLUMN},
        "action_uuid": str(latest.get("action_uuid", "")),
    }


class _State(ActionVisState):
    """Chart binding vars for the OER simulator."""

    chart_spec: dict = {}
    chart_url: str = ""
    version: int = 0
    action_uuid: str = ""

    def panel_key(self) -> str:
        """Session-scoped buffer-store key; see VisPanelState.panel_key."""
        return panel_id(self.server_key_default, self.router.session.client_token)

    def pull(self, ingest) -> None:
        """Recompute the chart payload from the trailing window."""
        cols = extract(ingest, self.window_points)
        self.version += 1
        payload = plots.time_series(
            cols["x"],
            cols["series"],
            x_label="t (s)",
            y_label="value",
            x_is_epoch=False,
            panel_id=self.panel_key(),
            version=self.version,
        )
        self.chart_spec = payload.spec
        self.chart_url = payload.buffer_url
        self.action_uuid = cols["action_uuid"]


STATE_BASE = _State


def build(server_key: str, state_cls):
    """Render the panel.

    Args:
        server_key: Action server this panel reads.
        state_cls: Generated state class bound to ``server_key``.

    Returns:
        rx.Component: The panel card.
    """
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading(f"Action: {server_key}", size="4"),
                rx.badge(state_cls.connection),
                rx.spacer(),
                rx.input(
                    default_value=str(state_cls.window_points),
                    on_blur=state_cls.on_window_points,
                    placeholder="window points",
                    width="10em",
                ),
                width="100%",
                align="center",
                spacing="3",
            ),
            rx.cond(
                state_cls.error != "",
                rx.text(state_cls.error, color_scheme="red"),
            ),
            plots.chart(state_cls.chart_spec, state_cls.chart_url, height=320),
            width="100%",
            spacing="3",
            on_mount=state_cls.render_loop,
            on_unmount=state_cls.stop_loop,
        ),
        width="100%",
    )
