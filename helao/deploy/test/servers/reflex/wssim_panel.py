"""Reflex panel for the websocket simulator's live datastream.

Reflex port of ``servers/visualizer/wssim_live_vis.py``: the ``series_<i>``
columns plotted against time, plus a latest-value table. The two coexist; a
station picks one through its config.
"""

__all__ = ["WS_PATH", "STATE_BASE", "build", "extract", "panel_id"]

import numpy as np
import reflex as rx

from helao.core.servers.reflex import plots
from helao.core.servers.reflex.state import LiveVisState

WS_PATH = "ws_live"

#: Column excluded from the plotted series set: it is the x axis.
X_COLUMN = "epoch"


def panel_id(server_key: str) -> str:
    """Stable buffer-store identity for this panel.

    Must not vary across renders: a shifting id would orphan store entries.
    """
    return f"wssim-{server_key}"


def extract(ingest, window: int) -> dict:
    """Pull the x column and every other numeric column from the ring buffer.

    Args:
        ingest: The panel's :class:`WsIngest`.
        window: Number of trailing rows to read.

    Returns:
        dict: ``{"epoch": np.ndarray, "series": {name: np.ndarray}}``.
    """
    snap = ingest.buffer.snapshot(window)
    return {
        "epoch": snap.get(X_COLUMN, np.empty(0)),
        "series": {k: v for k, v in snap.items() if k != X_COLUMN},
    }


class _State(LiveVisState):
    """Chart binding vars plus the latest-value table."""

    chart_spec: dict = {}
    chart_url: str = ""
    version: int = 0
    table_rows: list = []

    def pull(self, ingest) -> None:
        """Recompute the chart payload and the latest-value table."""
        cols = extract(ingest, self.window_points)
        self.version += 1
        payload = plots.time_series(
            cols["epoch"],
            cols["series"],
            x_label="Time (HH:MM:SS)",
            y_label="value",
            panel_id=panel_id(self.server_key_default),
            version=self.version,
        )
        self.chart_spec = payload.spec
        self.chart_url = payload.buffer_url
        self.table_rows = [
            [name, f"{values[-1]:.6g}"]
            for name, values in cols["series"].items()
            if values.size
        ]


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
                rx.heading(f"Live: {server_key}", size="4"),
                rx.badge(state_cls.connection),
                rx.spacer(),
                rx.input(
                    default_value=str(state_cls.window_points),
                    on_blur=state_cls.on_window_points,
                    placeholder="window points",
                    width="10em",
                ),
                rx.input(
                    default_value=str(state_cls.update_rate),
                    on_blur=state_cls.on_update_rate,
                    placeholder="update sec",
                    width="8em",
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
            rx.data_table(
                data=state_cls.table_rows,
                columns=["name", "value"],
                pagination=False,
                search=False,
                sort=False,
            ),
            width="100%",
            spacing="3",
            on_mount=state_cls.render_loop,
            on_unmount=state_cls.stop_loop,
        ),
        width="100%",
    )
