from datetime import datetime


from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.ui.shared.palette import SERIES
from helao.ui.bokeh.vis import Vis
from ._live_panel import LivePanel
from helao.ui.bokeh.vis_subscriber import LiveVisualizer


class C_vis(LivePanel, LiveVisualizer):
    """Bokeh visualizer for NIDAQmx thermocouple channels.

    Subscribes to the action server's ``ws_live`` WebSocket and renders one
    line per channel listed in ``params.dev_monitor`` against time, with a
    latest-values data table. Common subscriber bring-up, widget callbacks,
    and the ingest loop are inherited from :class:`LiveVisualizer`.

    Attributes:
        data_dict_keys: ``datetime`` + sorted ``dev_monitor`` channel names.
        datasource: :class:`ColumnDataSource` backing the plot.
        datasource_table: :class:`ColumnDataSource` backing the table.
        layout: Composed Bokeh layout mounted on the document.
        input_max_points: Widget setting ``max_points``.
        input_update_rate: Widget setting ``update_rate``.
        plot: Bokeh ``figure`` for temperature vs time.
        table: Bokeh ``DataTable`` showing the latest values.
    """

    SUBSCRIBE_LABEL = "Temperature sensor visualizer"
    Y_LABEL = "Temperature (C)"

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Wire up data sources, widgets, plot layout, and start the WS ingest task.

        Args:
            vis_serv: Host :class:`Vis` server providing the Bokeh document.
            serv_key: Configuration key of the thermocouple action server.
                If the server is not in the config, ``__init__`` returns
                early without registering any roots.
        """
        super().__init__(vis_serv, serv_key)
        if not self.connected:
            return
        tserv_config = self.serv_config

        self.data_dict_keys = ["datetime"] + sorted(
            tserv_config.get("params", {}).get("dev_monitor", {}).keys()
        )
        self._build_panel()

        self._mount()
        self._add_plots()

    def add_points(self, datapackage_list: list):
        """Stream live thermocouple samples into the data source and table.

        Unpacks ``(value, epoch)`` tuples from each package, expands
        ``sim_dict`` payloads, and triggers a plot rebuild if no renderers
        are attached yet.

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

        self.datasource.stream(data_dict, rollover=self.max_points)
        keys = list(data_dict.keys())
        values = [data_dict[k][-1] for k in keys]
        table_data_dict = {"name": keys, "value": values}
        self.datasource_table.stream(table_data_dict, rollover=len(keys))
        if not self.plot.renderers:
            self._add_plots()

    def _add_plots(self):
        """Rebuild the figure with one solid line per monitored channel."""
        # clear legend
        if self.plot.renderers:
            self.plot.legend.items = []

        # remove all old lines
        self.plot.renderers = []

        colors = [SERIES[0], SERIES[1], SERIES[2], SERIES[3]]
        non_epoch_keys = [x for x in self.data_dict_keys if x not in ["datetime"]]
        for temp_key, color in zip(non_epoch_keys, colors):
            self.plot.line(
                x="datetime",
                y=temp_key,
                line_color=color,
                source=self.datasource,
                legend_label=temp_key,
            )
            self.plot.legend.border_line_alpha = 0.2
            self.plot.legend.background_fill_alpha = 0.2
