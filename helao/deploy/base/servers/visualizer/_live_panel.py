"""Shared panel scaffold for the single-plot-plus-table live visualizers.

``co2_vis``, ``mfc_vis``, ``power_supply_vis``, ``pressure_vis``, ``tec_vis`` and
``temp_vis`` differ only in their data keys, y-axis label, and how they draw
lines. Everything else (the two settings inputs, the time plot, the
latest-values table, the header link and the layout) lives here.
"""

from functools import partial
from typing import Any

from bokeh.layouts import Spacer, layout
from bokeh.models import ColumnDataSource, DatetimeTickFormatter, TextInput
from bokeh.models.widgets import DataTable, Div, TableColumn
from bokeh.plotting import figure

from helao.ui.bokeh.theme import SECTION_MARGIN, stretch_section
from helao.ui.bokeh.vis_subscriber import VisSubscriber
from helao.ui.shared.palette import PANEL_BG, panel_styles


class LivePanel(VisSubscriber):
    """Mixin placed before the ``LiveVisualizer``/``ActionVisualizer`` base.

    Class attributes:
        Y_LABEL: y-axis label of the time plot.
        TICK_FORMATS: ``DatetimeTickFormatter`` keyword arguments.

    Subclasses set ``self.data_dict_keys``, call :meth:`_build_panel`, then
    ``self._mount()`` (and ``self._add_plots()`` where they draw at start-up).
    """

    data_dict_keys: list
    Y_LABEL = ""
    TICK_FORMATS: dict[str, Any] = {"minutes": "%T", "hours": "%T"}

    def _add_plots(self):
        raise NotImplementedError

    def _extend_plot(self):
        """Hook for panels that add axes to ``self.plot`` before layout."""

    def _build_panel(self):
        """Create data sources, inputs, plot, table, and ``self.layout``."""
        self.datasource = ColumnDataSource(data={k: [] for k in self.data_dict_keys})
        self.datasource_table = ColumnDataSource(
            data={k: [] for k in ["name", "value"]}
        )

        self.input_max_points = TextInput(
            value=f"{self.max_points}",
            title="max datapoints",
            disabled=False,
            width=150,
            height=40,
        )
        self.input_max_points.on_change(
            "value",
            partial(self.callback_input_max_points, sender=self.input_max_points),
        )

        self.input_update_rate = TextInput(
            value=f"{self.update_rate}",
            title="update sec",
            disabled=False,
            width=150,
            height=40,
        )
        self.input_update_rate.on_change(
            "value",
            partial(self.callback_input_update_rate, sender=self.input_update_rate),
        )

        self.plot = figure(height=300, sizing_mode="stretch_width")
        self.plot.xaxis.formatter = DatetimeTickFormatter(**self.TICK_FORMATS)
        self.plot.xaxis.axis_label = "Time (HH:MM:SS)"
        self.plot.yaxis.axis_label = self.Y_LABEL
        self._extend_plot()

        self.table = DataTable(
            source=self.datasource_table,
            columns=[
                TableColumn(field="name", title="name"),
                TableColumn(field="value", title="value"),
            ],
            height=300,
            width=400,
        )
        docs_url = f"http://{self.host}:{self.port}/docs#/"
        server_link = f'<a href="{docs_url}" target="_blank">\'{self.serv_key}\'</a>'
        headerbar = f"<b>Live vis module for server {server_link}</b>"
        self.layout = layout(
            [
                [Div(text=headerbar, sizing_mode="stretch_width", height=15)],
                [self.input_max_points, self.input_update_rate],
                Spacer(height=10),
                [self.plot, Spacer(width=20), self.table],
                Spacer(height=10),
            ],
            styles=panel_styles(PANEL_BG),
            margin=SECTION_MARGIN,
        )
        stretch_section(self.layout)

    def reset_plot(self, forceupdate: bool = False):
        """Rebuild the figure renderers (``forceupdate`` is accepted for parity)."""
        self._add_plots()
