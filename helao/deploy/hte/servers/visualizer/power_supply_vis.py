"""Bokeh live visualizer for a power-supply action server.

Exposes :class:`C_vis`, a per-server visualizer that subscribes to
``ws_data`` and plots voltage/current traces alongside a latest-values table.
"""

from datetime import datetime
from functools import partial

from bokeh.models import TextInput
from bokeh.plotting import figure
from bokeh.models.widgets import Div
from bokeh.models.widgets import DataTable, TableColumn
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource, DatetimeTickFormatter

from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.framework.app.vis import Vis
from helao.framework.adapters.vis_subscriber import ActionVisualizer


class C_vis(ActionVisualizer):
    """Bokeh visualizer for a power-supply action server.

    Subscribes to the server's ``ws_data`` WebSocket and renders voltage and
    current traces against time, alongside a latest-values table. Common
    subscriber bring-up, widget callbacks, and the ingest loop are inherited
    from :class:`ActionVisualizer`.

    Attributes:
        data_dict_keys: Column names streamed into the plot source.
        datasource: :class:`ColumnDataSource` backing the time-series plot.
        datasource_table: :class:`ColumnDataSource` backing the latest-values table.
        layout: Composed Bokeh layout mounted on the document.
        input_max_points: Widget setting ``max_points``.
        input_update_rate: Widget setting ``update_rate``.
        plot: Bokeh ``figure`` for voltage/current vs time.
        table: Bokeh ``DataTable`` showing the most recent values.
    """

    SUBSCRIBE_LABEL = "Power supply visualizer"
    DEFAULT_UPDATE_RATE = 0.5

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Wire up data sources, widgets, plot layout, and start the WS ingest task.

        Args:
            vis_serv: Host :class:`Vis` server providing the Bokeh document.
            serv_key: Configuration key of the power-supply action server.
                If the server is not in the config, ``__init__`` returns
                early without registering any roots.
        """
        super().__init__(vis_serv, serv_key)
        if not self.connected:
            return
        pws_host = self.host
        pws_port = self.port

        # Common variables to monitor: voltage, current, power, status (if available)
        self.data_dict_keys = [
            "t_s",
            # "voltage",
            "current_a",
            # "status",
        ]
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

        self.plot = figure(height=300, width=500)
        self.plot.xaxis.formatter = DatetimeTickFormatter(
            minsec="%T",
            minutes="%T",
            hourmin="%T",
            hours="%T",
        )
        self.plot.xaxis.axis_label = "Time (HH:MM:SS)"
        self.plot.yaxis.axis_label = "Voltage (V) / Current (A)"

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
        docs_url = f"http://{pws_host}:{pws_port}/docs#/"
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
            background="#D6DBDF",
            width=1024,
        )

        self._mount()

    def add_points(self, datapackage_list: list):
        """Stream live power-supply samples into the data source and table.

        Unpacks ``(value, epoch)`` tuples from each package, expands
        ``sim_dict`` payloads, appends the latest sample to the data table,
        and rebuilds the plot renderers.

        Args:
            datapackage_list: List of dicts from the live WebSocket.
        """
        latest_epoch = 0
        data_dict = {k: [] for k in self.data_dict_keys}
        for datapackage in datapackage_list:
            # expected datapackage: dict with keys like voltage, current_a, power_w, status, each has (value, epoch)
            for datalab, (dataval, epochsec) in datapackage.items():
                if datalab == "sim_dict":
                    for k, v in dataval.items():
                        data_dict[k].append(v)
                elif isinstance(dataval, list):
                    data_dict[datalab] += dataval
                else:
                    if datalab in data_dict:
                        data_dict[datalab].append(dataval)
                latest_epoch = max([epochsec, latest_epoch])
            data_dict["datetime"].append(datetime.fromtimestamp(latest_epoch))

        self.datasource.stream(data_dict, rollover=self.max_points)
        keys = list(data_dict.keys())
        values = [data_dict[k][-1] if len(data_dict[k]) > 0 else None for k in keys]
        table_data_dict = {"name": keys, "value": values}
        self.datasource_table.stream(table_data_dict, rollover=len(keys))
        self._add_plots()

    def _add_plots(self):
        """Rebuild the voltage/current traces on a shared time axis."""
        # clear legend
        if self.plot.renderers:
            self.plot.legend.items = []

        # remove all old lines
        self.plot.renderers = []

        # Plot voltage and current on the same plot
        self.plot.line(
            x="datetime",
            y="voltage",
            line_color="blue",
            legend_label="Voltage (V)",
            source=self.datasource,
        )
        self.plot.line(
            x="datetime",
            y="current",
            line_color="green",
            legend_label="Current (A)",
            source=self.datasource,
        )

    def reset_plot(self, forceupdate: bool = False):
        """Rebuild the figure renderers.

        Args:
            forceupdate: Accepted for parity with other visualizers; the plot
                is always rebuilt.
        """
        self._add_plots()
