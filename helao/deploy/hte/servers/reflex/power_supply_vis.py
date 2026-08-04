"""Reflex panel for a power supply's per-action data.

Reflex port of ``servers/visualizer/power_supply_vis.py``, which plots the
declared ``t_s`` and ``current_a`` columns.

Two things about the original are worth knowing before trusting either:

* It subclasses ``ActionVisualizer`` (``ws_data``) but its ``add_points``
  unpacks ``(value, epoch)`` tuples, which is the ``ws_live`` payload shape.
* It appends to ``data_dict["datetime"]``, a key absent from its own
  ``data_dict_keys``, so that line raises ``KeyError`` on the first packet.

This port follows the declared columns and the ``ws_data`` base class rather
than reproducing either. Only ``power_supply_test.yml`` names this panel.
"""

__all__ = ["WS_PATH", "STATE_BASE", "X_COLUMN", "build", "panel_id"]

import numpy as np
import reflex as rx

from helao.core.servers.reflex import plots
from helao.core.servers.reflex.state import ActionVisState
from helao.deploy.hte.servers.reflex._action import (
    MUTED_TEXT,
    X_COLUMN,
    latest_action_uuid,
)

WS_PATH = "ws_data"

Y_LABEL = "Voltage (V) / Current (A)"


def panel_id(server_key: str, session_token: str) -> str:
    """Buffer-store identity for this panel in one browser session."""
    return f"powersupply-{server_key}-{session_token}"


class _State(ActionVisState, mixin=True):
    """Chart binding vars for the power supply."""

    chart_spec: dict = {}
    chart_url: str = ""
    chart_layout: str = ""
    version: int = 0
    action_uuid: str = ""

    def panel_key(self) -> str:
        """Session-scoped buffer-store key; see VisPanelState.panel_key."""
        return panel_id(self.server_key, self.router.session.client_token)

    def pull(self, ingest) -> None:
        """Recompute the chart payload from the trailing window."""
        snapshot = ingest.buffer.snapshot(self.window_points)
        self.version += 1
        payload = plots.time_series(
            snapshot.get(X_COLUMN, np.empty(0)),
            {k: v for k, v in snapshot.items() if k != X_COLUMN},
            x_label="t (s)",
            y_label=Y_LABEL,
            x_is_epoch=False,
            panel_id=self.panel_key(),
            version=self.version,
        )
        self.chart_spec = payload.spec
        self.chart_url = payload.buffer_url
        self.chart_layout = payload.layout
        self.action_uuid = latest_action_uuid(ingest)


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
                rx.heading(f"Power supply: {server_key}", size="3"),
                rx.badge(state_cls.connection),
                rx.spacer(),
                rx.text(state_cls.action_uuid, size="1", class_name=MUTED_TEXT),
                rx.input(
                    default_value=state_cls.window_points.to_string(),
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
                rx.text(state_cls.error, class_name="text-red-600"),
            ),
            plots.chart(
                state_cls.chart_spec,
                state_cls.chart_url,
                state_cls.chart_layout,
                height=320,
            ),
            width="100%",
            spacing="3",
            on_mount=state_cls.render_loop,
            on_unmount=state_cls.stop_loop,
        ),
        width="100%",
    )
