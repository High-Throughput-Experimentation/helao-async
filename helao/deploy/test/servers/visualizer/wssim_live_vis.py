"""Bokeh visualizer module for the websocket simulator action server.

Subscribes to the simulator's ``ws_live`` websocket, plots the rolling
``series_<i>`` values against time, and mirrors the latest snapshot as a
two-column table.
"""

from datetime import datetime
from functools import partial

from bokeh.layouts import Spacer, layout
from bokeh.models import (
    ColumnDataSource,
    DatetimeTickFormatter,
    TextInput,
)
from bokeh.models.widgets import DataTable, Div, TableColumn
from bokeh.plotting import figure

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.core.servers.palette import PANEL_BG, SERIES, panel_styles
from helao.core.servers.vis import Vis
from helao.core.servers.vis_subscriber import LiveVisualizer


class C_vis(LiveVisualizer):
    """Live Bokeh visualizer for the websocket simulator action server.

    Builds widgets for ``max_points`` and ``update_rate``, a line plot of
    the synthetic series against time, and a key/value table for the
    latest sample. Common subscriber bring-up, widget callbacks, and the
    ingest loop are inherited from :class:`LiveVisualizer`.

    Attributes:
        datasource: ``ColumnDataSource`` backing the line plot.
        datasource_table: ``ColumnDataSource`` backing the key/value table.
        layout: Top-level Bokeh layout.
    """

    SUBSCRIBE_LABEL = "Live visualizer"

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Build the layout and start the polling coroutine.

        Args:
            vis_serv: Hosting visualizer server.
            serv_key: Name of the action server to visualize.
        """
        super().__init__(vis_serv, serv_key)
        if not self.connected:
            return
        host = self.host
        port = self.port

        self.data_dict_keys = ["datetime"] + [f"series_{i}" for i in range(6)]

        self.datasource = ColumnDataSource(data={k: [] for k in self.data_dict_keys})
        self.datasource_table = ColumnDataSource(
            data={k: [] for k in ["name", "value"]}
        )

        # create visual elements
        self.layout = []

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

        self.plot = figure(height=300, width=500, output_backend="webgl")
        self.plot.xaxis.formatter = DatetimeTickFormatter(
            minutes="%T",
            hours="%T",
        )
        self.plot.xaxis.axis_label = "Time (HH:MM:SS)"
        self.plot.yaxis.axis_label = "value"

        self.table = DataTable(
            source=self.datasource_table,
            columns=[
                TableColumn(field="name", title="name"),
                TableColumn(field="value", title="value"),
            ],
            height=300,
            width=400,
        )
        # combine all sublayouts into a single one
        docs_url = f"http://{host}:{port}/docs#/"
        server_link = f'<a href="{docs_url}" target="_blank">\'{self.serv_key}\'</a>'
        headerbar = f"<b>Live vis module for server {server_link}</b>"
        self.layout = layout(
            [
                [Div(text=headerbar, width=1004, height=15)],
                [self.input_max_points, self.input_update_rate],
                Spacer(height=10),
                [self.plot, Spacer(width=20), self.table],
                Spacer(height=10),
            ],
            styles=panel_styles(PANEL_BG),
            width=1024,
        )

        self._mount()
        self._add_plots()

    def add_points(self, datapackage_list: list):
        """Stream a batch of websocket messages into the plot and table.

        Flattens ``sim_dict`` entries into per-series lists, derives a
        ``datetime`` column from the latest epoch, and streams the result
        into both the line plot and the latest-value table.

        Args:
            datapackage_list: List of message dicts from the websocket.
        """
        latest_epoch = 0
        data_dict = {k: [] for k in self.data_dict_keys}
        for datapackage in datapackage_list:
            for datalab, (dataval, epochsec) in datapackage.items():
                if datalab == "sim_dict":
                    for k, v in dataval.items():
                        data_dict[k].append(v)
                elif isinstance(dataval, list):
                    data_dict[datalab] += dataval
                else:
                    data_dict[datalab].append(dataval)
                latest_epoch = max([epochsec, latest_epoch])
            data_dict["datetime"].append(datetime.fromtimestamp(latest_epoch))

        if latest_epoch != 0:
            self.datasource.stream(data_dict, rollover=self.max_points)
            keys = list(data_dict.keys())
            values = [data_dict[k][-1] for k in keys]
            table_data_dict = {"name": keys, "value": values}
            self.datasource_table.stream(table_data_dict, rollover=len(keys))

    def _add_plots(self):
        """Redraw the line plot, one renderer per non-time series."""
        # clear legend
        if self.plot.renderers:
            self.plot.legend.items = []

        # remove all old lines
        self.plot.renderers = []

        colors = [SERIES[0], SERIES[1], SERIES[2], SERIES[3]]
        non_epoch_keys = [x for x in self.data_dict_keys if x not in ["datetime"]]
        for pres_key, color in zip(non_epoch_keys, colors):
            self.plot.line(
                x="datetime",
                y=pres_key,
                line_color=color,
                source=self.datasource,
                legend_label=pres_key,
            )
            self.plot.legend.border_line_alpha = 0.2
            self.plot.legend.background_fill_alpha = 0.2
