"""Reflex panel for the NI-DAQmx cell array's per-action data.

Reflex port of ``servers/visualizer/nidaqmx_vis.py``: four figures -- the
running action's cell voltages and currents, and the previous action's -- with
a per-cell selector above them. Named for the same ``action_vis`` config value
the Bokeh module answers to, so a station needs no config change.
"""

__all__ = ["WS_PATH", "STATE_BASE", "X_COLUMN", "build", "panel_id"]

import numpy as np
import reflex as rx

from helao.core.servers.reflex import plots
from helao.core.servers.reflex.state import ActionVisState
from helao.deploy.hte.servers.reflex._action import (
    CURRENT_PATTERN,
    VOLTAGE_PATTERN,
    X_COLUMN,
    cell_numbers,
    latest_action_uuid,
    select_cells,
    split_on_restart,
)

WS_PATH = "ws_data"


def panel_id(server_key: str, session_token: str) -> str:
    """Buffer-store identity for this panel in one browser session.

    Four charts share this session but each takes its own suffix: the store
    holds one frame per key, so two charts under one key would overwrite each
    other into a frozen render.
    """
    return f"nidaqmx-{server_key}-{session_token}"


class _State(ActionVisState, mixin=True):
    """Four chart bindings, the cell selector, and the two action UUIDs.

    A mixin, and it must stay one: a var on a concrete ``rx.State`` is shared
    by every substate under it, so two NI-DAQmx servers on one page would
    share a chart.
    """

    volt_spec: dict = {}
    volt_url: str = ""
    volt_layout: str = ""
    current_spec: dict = {}
    current_url: str = ""
    current_layout: str = ""
    prev_volt_spec: dict = {}
    prev_volt_url: str = ""
    prev_volt_layout: str = ""
    prev_current_spec: dict = {}
    prev_current_url: str = ""
    prev_current_layout: str = ""

    version: int = 0
    action_uuid: str = ""
    #: Cells the stream carries, and the subset the operator wants drawn.
    available_cells: list[int] = []
    selected_cells: list[int] = []
    #: False until the first packet, so an untouched panel shows every cell
    #: rather than an empty chart the operator has to go and fix.
    _selection_touched: bool = False

    def panel_key(self) -> str:
        """Session-scoped buffer-store key; see VisPanelState.panel_key."""
        return panel_id(self.server_key, self.router.session.client_token)

    @rx.event
    def toggle_cell(self, cell: int):
        """Show or hide one cell."""
        self._selection_touched = True
        if cell in self.selected_cells:
            self.selected_cells = [c for c in self.selected_cells if c != cell]
        else:
            self.selected_cells = sorted(self.selected_cells + [cell])

    def _publish(self, name: str, x, series, y_label: str, suffix: str) -> None:
        """Render one figure and assign it into its three vars."""
        payload = plots.time_series(
            x,
            series,
            x_label="t (s)",
            y_label=y_label,
            x_is_epoch=False,
            panel_id=f"{self.panel_key()}-{suffix}",
            version=self.version,
        )
        setattr(self, f"{name}_spec", payload.spec)
        setattr(self, f"{name}_url", payload.buffer_url)
        setattr(self, f"{name}_layout", payload.layout)

    def pull(self, ingest) -> None:
        """Recompute all four figures from the trailing window."""
        snapshot = ingest.buffer.snapshot(self.window_points)
        x = snapshot.get(X_COLUMN, np.empty(0))
        series = {k: v for k, v in snapshot.items() if k != X_COLUMN}
        (prev_x, prev_series), (cur_x, cur_series) = split_on_restart(x, series)

        cells = cell_numbers(series, CURRENT_PATTERN) or cell_numbers(
            series, VOLTAGE_PATTERN
        )
        self.available_cells = cells
        if not self._selection_touched:
            self.selected_cells = cells

        self.version += 1
        picked = self.selected_cells
        self._publish(
            "volt",
            cur_x,
            select_cells(cur_series, VOLTAGE_PATTERN, picked),
            "Ecell (V)",
            "volt",
        )
        self._publish(
            "current",
            cur_x,
            select_cells(cur_series, CURRENT_PATTERN, picked),
            "Icell (A)",
            "current",
        )
        self._publish(
            "prev_volt",
            prev_x,
            select_cells(prev_series, VOLTAGE_PATTERN, picked),
            "Ecell (V)",
            "prevvolt",
        )
        self._publish(
            "prev_current",
            prev_x,
            select_cells(prev_series, CURRENT_PATTERN, picked),
            "Icell (A)",
            "prevcurrent",
        )
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

    def figure(spec, url, layout, title):
        return rx.vstack(
            rx.text(title, size="2", weight="medium"),
            plots.chart(spec, url, layout, height=260),
            width="100%",
            spacing="1",
        )

    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading(f"Cells: {server_key}", size="4"),
                rx.badge(state_cls.connection),
                rx.spacer(),
                rx.text(state_cls.action_uuid, size="1", color_scheme="gray"),
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
            rx.hstack(
                rx.text("cells:", size="2"),
                rx.foreach(
                    state_cls.available_cells,
                    lambda cell: rx.checkbox(
                        cell.to_string(),
                        checked=state_cls.selected_cells.contains(cell),
                        on_change=state_cls.toggle_cell(cell),
                    ),
                ),
                spacing="3",
                align="center",
                wrap="wrap",
            ),
            rx.cond(
                state_cls.error != "",
                rx.text(state_cls.error, color_scheme="red"),
            ),
            rx.hstack(
                figure(
                    state_cls.volt_spec,
                    state_cls.volt_url,
                    state_cls.volt_layout,
                    "voltage (this action)",
                ),
                figure(
                    state_cls.current_spec,
                    state_cls.current_url,
                    state_cls.current_layout,
                    "current (this action)",
                ),
                width="100%",
                spacing="3",
            ),
            rx.hstack(
                figure(
                    state_cls.prev_volt_spec,
                    state_cls.prev_volt_url,
                    state_cls.prev_volt_layout,
                    "voltage (previous action)",
                ),
                figure(
                    state_cls.prev_current_spec,
                    state_cls.prev_current_url,
                    state_cls.prev_current_layout,
                    "current (previous action)",
                ),
                width="100%",
                spacing="3",
            ),
            width="100%",
            spacing="3",
            on_mount=state_cls.render_loop,
            on_unmount=state_cls.stop_loop,
        ),
        width="100%",
    )
