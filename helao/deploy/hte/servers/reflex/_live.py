"""Shared machinery for the hte deployment's Reflex live panels.

The four ``ws_live`` visualizers -- CO2, mass-flow, pressure, temperature --
are one panel with four sets of labels: a time series of every streamed column,
an optional rolling mean over some of them, and a latest-value table. That
shape lives here once, and each panel module is a declaration over it.

Panels are named exactly as the ``live_vis`` value in the station configs
(``co2_vis``, ``mfc_vis``, ...), because ``resolve_panel_module`` looks them up
under ``servers/reflex/`` while the Bokeh stack keeps using
``servers/visualizer/``. A station therefore needs no config change to gain
these -- only a ``reflex:`` server entry.
"""

__all__ = [
    "FWIN",
    "X_COLUMN",
    "rolling_mean",
    "mean_name",
    "suffix_matcher",
    "every_column",
    "no_column",
    "series_for",
    "latest_rows",
    "make_live_panel",
]

import numpy as np
import reflex as rx
import scipy.ndimage as ndi

from helao.core.servers.palette import reflex_header_class, reflex_table_class
from helao.core.servers.reflex import plots
from helao.core.servers.reflex.state import LiveVisState, assign

#: Table hue, keyed by kind like every other Reflex table. ``server`` rather
#: than ``action``: this is one action server's latest live values, read on
#: ``/live`` while nothing in particular is running, not the output of an
#: action.
_TABLE_KIND = "server"
_HEADER_CLASS = reflex_header_class(_TABLE_KIND)
_TABLE_CLASS = reflex_table_class(_TABLE_KIND)

#: Height of the latest-value scroll area. Bounded so a stream that gains
#: columns does not push the panels below it down the page as it grows.
_TABLE_HEIGHT = "12em"

#: Rolling-mean width, matching the Bokeh visualizers' ``FWIN``.
FWIN = 20

#: The x column the ``ws_live`` normalizer produces.
X_COLUMN = "epoch"

#: Suffix marking a column as a computed mean.
MEAN_SUFFIX = "_mean"


def rolling_mean(values: np.ndarray, window: int = FWIN) -> np.ndarray:
    """Smooth ``values`` with a uniform filter, or return them unchanged.

    With less history than the filter is wide, the Bokeh visualizers plot the
    raw values rather than a mean computed from too little data
    (``len(mvec) >= FWIN``); this keeps that behaviour.

    **Not bit-identical to the Bokeh version.** Bokeh filters the whole
    accumulated vector and streams the tail, while this filters the visible
    window. The two agree except at the leading edge of the window, where
    ``mode="nearest"`` has less history to reach back into. What a viewer sees
    is the window, so the difference is confined to its oldest points.
    """
    if values.size < window:
        return values
    return ndi.uniform_filter1d(values, window, mode="nearest")


def mean_name(column: str) -> str:
    """Name of the mean partner column, matching the Bokeh naming."""
    return f"{column}{MEAN_SUFFIX}"


def suffix_matcher(*suffixes: str):
    """Match columns ending with any of ``suffixes``."""

    def wants(column: str) -> bool:
        return any(column.endswith(suffix) for suffix in suffixes)

    return wants


def every_column(column: str) -> bool:
    """Match every column."""
    return True


def no_column(column: str) -> bool:
    """Match no column."""
    return False


def series_for(snapshot: dict, wants_mean=no_column, x_column: str = X_COLUMN):
    """Split a ring-buffer snapshot into an x array and plottable series.

    Args:
        snapshot: ``{column: np.ndarray}`` from the panel's ring buffer. The
            buffer is float64-only, so every column here is already numeric.
        wants_mean: Predicate choosing which columns get a rolling-mean
            partner. Defaults to none.
        x_column: Column used as the x axis, excluded from the series.

    Returns:
        tuple: ``(x, series)``. ``series`` is sorted by name so the chart's
        legend does not reshuffle between ticks, and a mean the stream already
        publishes is left alone rather than being recomputed over itself.
    """
    x = snapshot.get(x_column, np.empty(0))
    series = {
        name: values for name, values in sorted(snapshot.items()) if name != x_column
    }
    for name in list(series):
        if name.endswith(MEAN_SUFFIX) or not wants_mean(name):
            continue
        partner = mean_name(name)
        if partner in series:
            # The driver publishes its own mean. Recomputing would plot a mean
            # of a mean under a name that claims otherwise.
            continue
        series[partner] = rolling_mean(series[name])
    return x, dict(sorted(series.items()))


def latest_rows(series: dict) -> list:
    """Most recent value of each series, as table rows.

    Every cell is a string: Reflex serialises state to JSON, and ``rx.foreach``
    needs a concrete element type.
    """
    return [
        [name, f"{values[-1]:.6g}"] for name, values in series.items() if values.size
    ]


def make_live_panel(prefix: str, y_label: str, wants_mean=no_column):
    """Build one live panel's module contract.

    Args:
        prefix: Short name for the buffer-store key, unique per panel module.
        y_label: Y axis label, the only thing most of these panels differ by.
        wants_mean: Predicate choosing the columns that get a rolling mean.

    Returns:
        tuple: ``(state_base, build, panel_id)`` for the module to publish.
    """

    def panel_id(server_key: str, session_token: str) -> str:
        """Buffer-store identity for this panel in one browser session.

        Scoped per session: the store keeps one frame per key while the
        version counter lives in per-session state, so two tabs sharing a key
        would 404 each other into a permanently frozen chart.
        """
        return f"{prefix}-{server_key}-{session_token}"

    class _State(LiveVisState, mixin=True):
        """Chart binding vars plus the latest-value table.

        A mixin, and it must stay one: a var declared on a concrete
        ``rx.State`` is shared by every substate under it, so every panel on
        the page would end up sharing one chart.
        """

        chart_spec: dict = {}
        chart_url: str = ""
        chart_layout: str = ""
        version: int = 0
        table_rows: list[list[str]] = []

        def panel_key(self) -> str:
            """Session-scoped buffer-store key; see VisPanelState.panel_key."""
            return panel_id(self.server_key, self.router.session.client_token)

        def pull(self, ingest) -> None:
            """Recompute the chart payload and the latest-value table.

            Every write goes through ``assign``. Reflex marks a var dirty on
            assignment, not on change, so an unconditional write published a
            delta on every tick with nothing new in it -- and ``chart_layout``
            never changes at all, while ``table_rows`` holds still for as long
            as the stream repeats a value.
            """
            x, series = series_for(
                ingest.buffer.snapshot(self.window_points), wants_mean=wants_mean
            )
            self.version += 1
            payload = plots.time_series(
                x,
                series,
                x_label="Time (HH:MM:SS)",
                y_label=y_label,
                panel_id=self.panel_key(),
                version=self.version,
            )
            assign(self, "chart_spec", payload.spec)
            assign(self, "chart_url", payload.buffer_url)
            assign(self, "chart_layout", payload.layout)
            assign(self, "table_rows", latest_rows(series))

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
                    rx.heading(f"{y_label}: {server_key}", size="3"),
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
                # Bound once. The payload is produced in pull(), per tick.
                plots.chart(
                    state_cls.chart_spec,
                    state_cls.chart_url,
                    state_cls.chart_layout,
                    height=320,
                ),
                # A Radix ``rx.table``, not ``rx.data_table`` (gridjs), for the
                # reason sample_vis was ported for: gridjs rebuilds its whole
                # grid on *any* state delta, not only on a change to the var it
                # renders. A chart panel publishes a fresh spec and buffer URL
                # on every packet, so the table beside it rebuilt at the render
                # cadence and changed height as it did -- which reads at the
                # bench as the panel bouncing, and did so even here where the
                # table was empty. Radix also takes ``class_name``, so this
                # picks up the stack's shared table styling; gridjs drops it.
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

    return _State, build, panel_id
