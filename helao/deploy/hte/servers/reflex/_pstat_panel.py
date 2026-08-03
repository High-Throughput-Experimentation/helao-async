"""The Reflex panel both potentiostat visualizers are built from.

Kept apart from ``_pstat.py`` so the logic that can be wrong -- axis defaults,
column selection, channel routing -- stays importable and testable without
Reflex's app machinery. This module is state assignment and layout only.
"""

__all__ = ["make_pstat_panel"]

import numpy as np
import reflex as rx

from helao.core.servers.reflex import plots
from helao.core.servers.reflex.state import ActionVisState, assign
from helao.deploy.hte.servers.reflex._action import (
    X_COLUMN,
    latest_action_uuid,
    segment_trace_groups,
)
from helao.deploy.hte.servers.reflex._pstat import (
    axis_defaults,
    channels_in,
    plottable_columns,
    select_channel,
    xy_pair,
)

#: Plots drawn per channel. More would not fit side by side legibly.
MAX_CHANNELS = 4


def make_pstat_panel(
    prefix: str, title: str, columns: list, axis_map: dict, per_channel: bool
):
    """Build one potentiostat panel's module contract.

    Args:
        prefix: Short name for the buffer-store key, unique per panel module.
        title: Heading shown above the panel.
        columns: Columns this server streams, in selector order.
        axis_map: Action name -> default ``(x, y)`` pair.
        per_channel: Whether to draw one plot pair per hardware channel.

    Returns:
        tuple: ``(state_base, build, panel_id)`` for the module to publish.
    """

    def panel_id(server_key: str, session_token: str) -> str:
        """Buffer-store identity for this panel in one browser session."""
        return f"{prefix}-{server_key}-{session_token}"

    class _State(ActionVisState, mixin=True):
        """Axis selection, per-channel chart payloads, and the action UUID.

        A mixin, and it must stay one: a var on a concrete ``rx.State`` is
        shared by every substate under it, so two potentiostats on one page
        would share their axes.
        """

        #: One entry per drawn chart, in render order. Charts are addressed by
        #: index rather than by named vars because BioLogic's channel count is
        #: only known from the stream.
        chart_specs: list[dict] = []
        chart_urls: list[str] = []
        chart_layouts: list[str] = []
        chart_titles: list[str] = []

        version: int = 0
        action_uuid: str = ""
        action_name: str = ""
        axis_options: list[str] = columns
        x_column: str = ""
        y_column: str = ""
        #: False until the operator picks an axis, after which the technique's
        #: default stops overriding their choice on the next action.
        _axes_chosen: bool = False

        def panel_key(self) -> str:
            """Session-scoped buffer-store key; see VisPanelState.panel_key."""
            return panel_id(self.server_key, self.router.session.client_token)

        @rx.event
        def set_x(self, value: str):
            """Choose the x column."""
            self._axes_chosen = True
            self.x_column = value
            self.request_pull()

        @rx.event
        def set_y(self, value: str):
            """Choose the y column."""
            self._axes_chosen = True
            self.y_column = value
            self.request_pull()

        def _figures(self, snapshot: dict) -> list:
            """Build ``(title, traces)`` for every chart this panel draws.

            Two charts per source, as the Bokeh panel had: the running action
            and the one before it, each with its own axes so a short action is
            not squashed by a long predecessor. That costs a WebGL context per
            chart and browsers cap how many are live -- see
            :func:`segment_trace_groups` -- so a page carrying many of these
            panels is the thing to watch, not the panel itself.
            """
            if per_channel:
                channels = channels_in(snapshot)[:MAX_CHANNELS]
                sources = (
                    [(f"channel {c}", select_channel(snapshot, c)) for c in channels]
                    if channels
                    else [("", snapshot)]
                )
            else:
                sources = [("", snapshot)]

            def pick(segment_x, segment):
                # split_on_restart hands x back separately; xy_pair looks
                # columns up by name, so put it back under its own.
                merged = {**segment, X_COLUMN: segment_x}
                return xy_pair(merged, self.x_column, self.y_column)

            figures = []
            for label, source in sources:
                x_all = source.get(X_COLUMN, np.empty(0))
                series_all = {k: v for k, v in source.items() if k != X_COLUMN}
                # suffix_names=False: the chart title already names the
                # segment, so repeating it in every legend entry is noise.
                for suffix, traces in segment_trace_groups(
                    x_all, series_all, pick, suffix_names=False
                ):
                    figures.append((f"{label} {suffix}".strip(), traces))
            return figures

        def pull(self, ingest) -> None:
            """Recompute every chart from the trailing window."""
            snapshot = ingest.buffer.snapshot(self.window_points)
            # Written only on change; see state.assign. These are constant for
            # the whole of an action, so an unconditional write published a
            # delta on every tick with nothing new in it.
            assign(self, "action_uuid", latest_action_uuid(ingest))
            latest = ingest.rows.latest() or {}
            assign(
                self,
                "action_name",
                str(latest.get("action_name", "") or self.action_name),
            )

            present = plottable_columns(snapshot, columns)
            if present and not set(present) & set(columns):
                # The stream carries none of the columns this panel declares.
                # Falling back to the declared list plots a blank chart with
                # nothing on screen to explain it -- the failure this panel is
                # least able to afford, since a blank chart is also what "no
                # data yet" looks like. Draw what did arrive, and say so.
                assign(
                    self,
                    "error",
                    "stream carries none of the declared columns "
                    f"({', '.join(columns)}); plotting {', '.join(present)}",
                )
            if present:
                # The selectors offer what the stream actually carries, so an
                # operator overriding the default is not choosing from a list
                # of columns that are not there.
                assign(self, "axis_options", present)
            if not self._axes_chosen or self.x_column not in snapshot:
                default_x, default_y = axis_defaults(
                    axis_map, self.action_name, present
                )
                assign(self, "x_column", default_x)
                assign(self, "y_column", default_y)

            self.version += 1
            specs, urls, layouts, titles = [], [], [], []
            for index, (heading, series) in enumerate(self._figures(snapshot)):
                # plots.traces, not time_series: the two action segments have
                # different lengths and so cannot share one x column.
                payload = plots.traces(
                    series,
                    kind="line",
                    x_label=self.x_column,
                    y_label=self.y_column,
                    panel_id=f"{self.panel_key()}-{index}",
                    version=self.version,
                )
                specs.append(payload.spec)
                urls.append(payload.buffer_url)
                layouts.append(payload.layout)
                titles.append(heading)
            self.chart_specs = specs
            self.chart_urls = urls
            self.chart_layouts = layouts
            self.chart_titles = titles

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
                    rx.heading(f"{title}: {server_key}", size="4"),
                    rx.badge(state_cls.connection),
                    rx.spacer(),
                    rx.text(state_cls.action_name, size="1"),
                    rx.text(state_cls.action_uuid, size="1", color_scheme="gray"),
                    width="100%",
                    align="center",
                    spacing="3",
                ),
                rx.hstack(
                    rx.text("x:", size="2"),
                    rx.select(
                        state_cls.axis_options,
                        value=state_cls.x_column,
                        on_change=state_cls.set_x,
                        width="9em",
                    ),
                    rx.text("y:", size="2"),
                    rx.select(
                        state_cls.axis_options,
                        value=state_cls.y_column,
                        on_change=state_cls.set_y,
                        width="9em",
                    ),
                    rx.input(
                        default_value=state_cls.window_points.to_string(),
                        on_blur=state_cls.on_window_points,
                        placeholder="window points",
                        width="10em",
                    ),
                    spacing="3",
                    align="center",
                ),
                rx.cond(
                    state_cls.error != "",
                    rx.text(state_cls.error, color_scheme="red"),
                ),
                rx.hstack(
                    rx.foreach(
                        state_cls.chart_titles,
                        lambda heading, index: rx.vstack(
                            rx.text(heading, size="2", weight="medium"),
                            plots.chart(
                                state_cls.chart_specs[index],
                                state_cls.chart_urls[index],
                                state_cls.chart_layouts[index],
                                height=260,
                            ),
                            width="100%",
                            spacing="1",
                        ),
                    ),
                    width="100%",
                    spacing="3",
                    wrap="wrap",
                ),
                width="100%",
                spacing="3",
                on_mount=state_cls.render_loop,
                on_unmount=state_cls.stop_loop,
            ),
            width="100%",
        )

    return _State, build, panel_id
