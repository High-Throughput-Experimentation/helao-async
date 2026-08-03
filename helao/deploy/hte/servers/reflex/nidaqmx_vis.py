"""Reflex panel for the NI-DAQmx cell array's per-action data.

Reflex port of ``servers/visualizer/nidaqmx_vis.py``: two figures -- cell
voltages and cell currents -- each drawing the running action beside the
previous one as separate traces, with a per-cell selector above them. Named
for the same ``action_vis`` config value the Bokeh module answers to, so a
station needs no config change.
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
    segment_traces,
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
    """Two chart bindings, the cell selector, and the action UUID.

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

    def _publish(self, name: str, series, y_label: str, suffix: str) -> None:
        """Render one figure and assign it into its three vars.

        plots.traces, not time_series: the figure carries both action segments
        and they have different lengths, so there is no shared x column.
        """
        payload = plots.traces(
            series,
            kind="line",
            x_label="t (s)",
            y_label=y_label,
            panel_id=f"{self.panel_key()}-{suffix}",
            version=self.version,
        )
        setattr(self, f"{name}_spec", payload.spec)
        setattr(self, f"{name}_url", payload.buffer_url)
        setattr(self, f"{name}_layout", payload.layout)

    def pull(self, ingest) -> None:
        """Recompute both figures from the trailing window.

        Two charts, not four: each one draws the current action beside the
        previous one as separate traces. See :func:`segment_traces`.
        """
        snapshot = ingest.buffer.snapshot(self.window_points)
        x = snapshot.get(X_COLUMN, np.empty(0))
        series = {k: v for k, v in snapshot.items() if k != X_COLUMN}

        cells = cell_numbers(series, CURRENT_PATTERN) or cell_numbers(
            series, VOLTAGE_PATTERN
        )
        self.available_cells = cells
        if not self._selection_touched:
            self.selected_cells = cells

        self.version += 1
        picked = self.selected_cells

        def by_pattern(pattern):
            return lambda seg_x, seg: (seg_x, select_cells(seg, pattern, picked))

        self._publish(
            "volt",
            segment_traces(x, series, by_pattern(VOLTAGE_PATTERN)),
            "Ecell (V)",
            "volt",
        )
        self._publish(
            "current",
            segment_traces(x, series, by_pattern(CURRENT_PATTERN)),
            "Icell (A)",
            "current",
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
                    "voltage",
                ),
                figure(
                    state_cls.current_spec,
                    state_cls.current_url,
                    state_cls.current_layout,
                    "current",
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
