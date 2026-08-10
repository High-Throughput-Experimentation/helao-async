"""Reflex panel for the websocket simulator's live datastream.

Reflex port of ``servers/visualizer/wssim_live_vis.py``: the ``series_<i>``
columns plotted against time, plus a latest-value table. The two coexist; a
station picks one through its config.
"""

__all__ = ["WS_PATH", "STATE_BASE", "build", "extract", "panel_id"]

import numpy as np
import reflex as rx

from helao.core.servers.palette import reflex_header_class, reflex_table_class
from helao.core.servers.reflex import plots
from helao.core.servers.reflex.state import LiveVisState, assign

WS_PATH = "ws_live"

#: Column excluded from the plotted series set: it is the x axis.
X_COLUMN = "epoch"

#: Table hue, keyed by kind like every other Reflex table. ``server``: this is
#: one action server's latest live values, read while nothing in particular is
#: running.
_TABLE_KIND = "server"
_HEADER_CLASS = reflex_header_class(_TABLE_KIND)
_TABLE_CLASS = reflex_table_class(_TABLE_KIND)

#: Height of the latest-value scroll area, bounded so a stream that gains
#: columns does not push the panels below it down the page as it grows.
_TABLE_HEIGHT = "12em"


def panel_id(server_key: str, session_token: str) -> str:
    """Buffer-store identity for this panel in one browser session.

    Stable across renders -- a shifting id orphans store entries -- but scoped
    per session, because the store holds one frame per key while the version
    counter lives in per-session state. Two tabs sharing a key overwrite each
    other and 404 each other into a permanently frozen chart.
    """
    return f"wssim-{server_key}-{session_token}"


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


class _State(LiveVisState, mixin=True):
    """Chart binding vars plus the latest-value table."""

    chart_spec: dict = {}
    chart_url: str = ""
    chart_layout: str = ""
    version: int = 0
    #: Annotated to its element type, not a bare ``list``: ``rx.foreach`` needs
    #: one, and a bare ``list`` fails the *frontend build* with
    #: ``ForeachVarError`` rather than at import -- so it looks fine until
    #: ``reflex export`` runs.
    table_rows: list[list[str]] = []

    def panel_key(self) -> str:
        """Session-scoped buffer-store key; see VisPanelState.panel_key."""
        return panel_id(self.server_key, self.router.session.client_token)

    def pull(self, ingest) -> None:
        """Recompute the chart payload and the latest-value table.

        Every write goes through ``assign``. Reflex marks a var dirty on
        assignment, not on change, so an unconditional write published a delta
        on every tick with nothing new in it -- and ``chart_layout`` never
        changes at all.
        """
        cols = extract(ingest, self.window_points)
        self.version += 1
        payload = plots.time_series(
            cols["epoch"],
            cols["series"],
            x_label="Time (HH:MM:SS)",
            y_label="value",
            panel_id=self.panel_key(),
            version=self.version,
        )
        assign(self, "chart_spec", payload.spec)
        assign(self, "chart_url", payload.buffer_url)
        assign(self, "chart_layout", payload.layout)
        assign(
            self,
            "table_rows",
            [
                [name, f"{values[-1]:.6g}"]
                for name, values in cols["series"].items()
                if values.size
            ],
        )


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
                rx.heading(f"Live: {server_key}", size="3"),
                rx.badge(state_cls.connection),
                rx.spacer(),
                rx.input(
                    default_value=state_cls.window_points.to_string(),
                    on_blur=state_cls.on_window_points,
                    placeholder="window points",
                    width="10em",
                ),
                rx.input(
                    default_value=state_cls.update_rate.to_string(),
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
                rx.text(state_cls.error, class_name="text-red-600"),
            ),
            plots.chart(
                state_cls.chart_spec,
                state_cls.chart_url,
                state_cls.chart_layout,
                height=320,
            ),
            # A Radix ``rx.table``, not ``rx.data_table`` (gridjs): gridjs
            # rebuilds its whole grid on *any* state delta, not only on a
            # change to the var it renders. A chart panel publishes a fresh
            # spec and buffer URL on every packet, so the table beside it
            # rebuilt at the render cadence and changed height as it did --
            # which reads at the bench as the panel bouncing. Radix also takes
            # ``class_name``, so this picks up the stack's shared table
            # styling; gridjs drops it.
            rx.scroll_area(
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            *[
                                rx.table.column_header_cell(
                                    col, class_name=_HEADER_CLASS
                                )
                                for col in ("name", "value")
                            ]
                        )
                    ),
                    rx.table.body(
                        rx.foreach(
                            state_cls.table_rows,
                            lambda row: rx.table.row(
                                rx.foreach(row, lambda cell: rx.table.cell(cell))
                            ),
                        )
                    ),
                    width="100%",
                    size="1",
                    class_name=_TABLE_CLASS,
                ),
                type="auto",
                scrollbars="vertical",
                height=_TABLE_HEIGHT,
                width="100%",
            ),
            width="100%",
            spacing="3",
            on_mount=state_cls.render_loop,
            on_unmount=state_cls.stop_loop,
        ),
        width="100%",
    )
