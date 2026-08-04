from datetime import datetime
from functools import partial

import numpy as np
import scipy.ndimage as ndi
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

FWIN = 20

# Preserves each analog channel's plotted hue: the original per-channel colour
# list was ["red", "blue", "green", "orange", "purple", "cyan", "magenta"];
# these are the matching SERIES indices, in the same order.
_CHANNEL_SERIES_IDX = (0, 1, 2, 3, 4, 8, 6)


class C_vis(LiveVisualizer):
    """Bokeh visualizer for analog pressure-sensor channels exposed by a Galil IO server.

    Subscribes to the action server's ``ws_live`` WebSocket and renders one
    raw and one rolling-mean trace per analog input channel listed under
    ``params.dev_ai``, alongside a latest-values data table. Common subscriber
    bring-up, widget callbacks, and the ingest loop are inherited from
    :class:`LiveVisualizer`.

    Attributes:
        ai_keys: Sorted list of analog input channel names from the action
            server's ``dev_ai`` parameter.
        mean_ai_keys: ``"{name}_mean"`` partner columns for ``ai_keys``.
        data_dict_keys: Combined ``datetime`` + raw + mean column names.
        datasource: :class:`ColumnDataSource` backing the plot.
        datasource_table: :class:`ColumnDataSource` backing the table.
        layout: Composed Bokeh layout mounted on the document.
        input_max_points: Widget setting ``max_points``.
        input_update_rate: Widget setting ``update_rate``.
        plot: Bokeh ``figure`` for pressure vs time.
        table: Bokeh ``DataTable`` showing the latest values.
    """

    SUBSCRIBE_LABEL = "Pressure sensor visualizer"

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Wire up data sources, widgets, plot layout, and start the WS ingest task.

        Args:
            vis_serv: Host :class:`Vis` server providing the Bokeh document.
            serv_key: Configuration key of the pressure-sensor action server.
                If the server is not in the config, ``__init__`` returns
                early without registering any roots.
        """
        super().__init__(vis_serv, serv_key)
        if not self.connected:
            return
        psrv_config = self.serv_config
        psrv_host = self.host
        psrv_port = self.port

        self.ai_keys = sorted(psrv_config.get("params", {}).get("dev_ai", {}).keys())
        self.mean_ai_keys = [f"{x}_mean" for x in self.ai_keys]
        self.data_dict_keys = ["datetime"] + self.ai_keys + self.mean_ai_keys
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
        self.plot.yaxis.axis_label = "Pressure (psi)"

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
        docs_url = f"http://{psrv_host}:{psrv_port}/docs#/"
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
        """Stream live pressure samples into the data source and table.

        Unpacks ``(value, epoch)`` tuples, expands ``sim_dict`` payloads,
        computes a ``FWIN``-point rolling mean for each analog input, and
        refreshes the latest-values table.

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
        for mvar in self.ai_keys:
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
        """Rebuild the pressure figure with raw and rolling-mean traces per channel."""
        # clear legend
        if self.plot.renderers:
            self.plot.legend.items = []

        # remove all old lines
        self.plot.renderers = []

        colors = [SERIES[i] for i in _CHANNEL_SERIES_IDX]
        non_epoch_keys = [
            x for x in self.data_dict_keys if x not in ["datetime"] + self.mean_ai_keys
        ]
        for pres_key, color in zip(non_epoch_keys, colors):
            self.plot.line(
                x="datetime",
                y=pres_key,
                line_color=color,
                line_dash="dotted",
                source=self.datasource,
                legend_label=pres_key,
            )
            self.plot.line(
                x="datetime",
                y=f"{pres_key}_mean",
                line_color=color,
                line_dash="solid",
                source=self.datasource,
                legend_label=f"{pres_key} rolling mean",
            )
            self.plot.legend.border_line_alpha = 0.2
            self.plot.legend.background_fill_alpha = 0.2

    def reset_plot(self, forceupdate: bool = False):
        """Rebuild the figure renderers.

        Args:
            forceupdate: Accepted for parity with other visualizers; the plot
                is always rebuilt.
        """
        self._add_plots()
