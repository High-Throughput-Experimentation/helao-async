from functools import partial
from datetime import datetime

import numpy as np
import scipy.ndimage as ndi

from bokeh.models import (
    TextInput,
)
from bokeh.plotting import figure
from bokeh.models.widgets import Div
from bokeh.models.widgets import DataTable, TableColumn
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource, DatetimeTickFormatter

from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.framework.app.vis import Vis
from helao.framework.adapters.vis_subscriber import LiveVisualizer

FWIN = 20


class C_vis(LiveVisualizer):
    """Bokeh visualizer for a CO2 sensor server's live datastream.

    Subscribes to the action server's ``ws_live`` WebSocket and renders a
    time-series plot of raw and rolling-mean CO2 concentration alongside a
    "latest values" data table. Common subscriber bring-up, widget callbacks,
    and the ingest loop are inherited from :class:`LiveVisualizer`.

    Attributes:
        data_dict_keys: Column names streamed into the plot source.
        datasource: :class:`ColumnDataSource` backing the time-series plot.
        datasource_table: :class:`ColumnDataSource` backing the latest-values table.
        layout: Composed Bokeh layout mounted on the document.
        input_max_points: Widget setting ``max_points``.
        input_update_rate: Widget setting ``update_rate``.
        plot: Bokeh ``figure`` for CO2 vs time.
        table: Bokeh ``DataTable`` showing the most recent values.
    """

    SUBSCRIBE_LABEL = "CO2 sensor visualizer"

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Wire up data sources, widgets, plot layout, and start the WS ingest task.

        Args:
            vis_serv: Host :class:`Vis` server providing the Bokeh document.
            serv_key: Configuration key of the CO2 action server to subscribe
                to. If the server is not in the config, ``__init__`` returns
                early without registering any roots.
        """
        super().__init__(vis_serv, serv_key)
        if not self.connected:
            return
        co2serv_host = self.host
        co2serv_port = self.port

        self.data_dict_keys = ["datetime", "co2_ppm", "co2_ppm_mean"]
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
            minutes="%T",
            hours="%T",
        )
        self.plot.xaxis.axis_label = "Time (HH:MM:SS)"
        self.plot.yaxis.axis_label = "CO2 (ppm)"

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
        docs_url = f"http://{co2serv_host}:{co2serv_port}/docs#/"
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
        self._add_plots()

    def add_points(self, datapackage_list: list):
        """Stream a batch of live CO2 samples into the data source and table.

        Unpacks ``(value, epoch)`` tuples from each package, expands
        ``sim_dict`` payloads, computes a ``FWIN``-point rolling mean for
        ``co2_ppm``, then streams the merged dict into ``self.datasource``
        and refreshes the latest-values table.

        Args:
            datapackage_list: List of dicts from the live WebSocket.
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
        for mvar in self.data_dict_keys:
            if mvar in ["co2_ppm"]:
                mvec = np.concatenate((self.datasource.data[mvar], data_dict[mvar]))
                if len(mvec) >= FWIN:
                    data_dict[f"{mvar}_mean"] = list(
                        ndi.uniform_filter1d(mvec, FWIN, mode="nearest")[
                            -len(data_dict[mvar]) :
                        ]
                    )
                else:
                    data_dict[f"{mvar}_mean"] = data_dict[mvar]

        self.datasource.stream(data_dict, rollover=self.max_points)
        keys = list(data_dict.keys())
        values = [data_dict[k][-1] for k in keys]
        table_data_dict = {"name": keys, "value": values}
        self.datasource_table.stream(table_data_dict, rollover=len(keys))

    def _add_plots(self):
        """Rebuild the CO2 vs time figure with raw and rolling-mean traces."""
        # clear legend
        if self.plot.renderers:
            self.plot.legend.items = []

        # remove all old lines
        self.plot.renderers = []

        self.plot.line(
            x="datetime",
            y="co2_ppm",
            line_color="red",
            legend_label="CO2 ppm (filtered)",
            source=self.datasource,
        )
        self.plot.line(
            x="datetime",
            y="co2_ppm_mean",
            line_color="blue",
            legend_label="CO2 ppm rolling mean",
        )
        self.plot.legend.border_line_alpha = 0.2
        self.plot.legend.background_fill_alpha = 0.2

    def reset_plot(self, forceupdate: bool = False):
        """Rebuild the figure renderers (e.g. after a configuration change).

        Args:
            forceupdate: Accepted for parity with other visualizers; the plot
                is always rebuilt.
        """
        self._add_plots()
