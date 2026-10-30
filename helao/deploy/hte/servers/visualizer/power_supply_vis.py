"""Bokeh live visualizer for a power-supply action server.

Exposes :class:`C_vis`, a per-server visualizer that subscribes to
``ws_data`` and plots voltage/current traces alongside a latest-values table.
"""

from datetime import datetime


from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.ui.shared.palette import SERIES
from helao.ui.bokeh.vis import Vis
from ._live_panel import LivePanel
from helao.ui.bokeh.vis_subscriber import ActionVisualizer


class C_vis(LivePanel, ActionVisualizer):
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
    Y_LABEL = "Voltage (V) / Current (A)"
    TICK_FORMATS = {
        "minsec": "%T",
        "minutes": "%T",
        "hourmin": "%T",
        "hours": "%T",
    }
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

        # Common variables to monitor: voltage, current, power, status (if available)
        # "datetime" first, as every sibling live panel does: `add_points`
        # appends one timestamp per package unconditionally, and the plots below
        # use it as the x axis, so omitting it raised KeyError on every call.
        self.data_dict_keys = [
            "datetime",
            "t_s",
            # "voltage",
            "current_a",
            # "status",
        ]
        self._build_panel()

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
            line_color=SERIES[1],
            legend_label="Voltage (V)",
            source=self.datasource,
        )
        self.plot.line(
            x="datetime",
            y="current",
            line_color=SERIES[2],
            legend_label="Current (A)",
            source=self.datasource,
        )
