from datetime import datetime

from bokeh.models import (
    LinearAxis,
    Range1d,
)

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.ui.shared.palette import SERIES
from helao.ui.bokeh.vis import Vis
from ._live_panel import LivePanel
from helao.ui.bokeh.vis_subscriber import LiveVisualizer

from ...drivers.temperature_control.mecom_driver import DEFAULT_QUERIES


class C_vis(LivePanel, LiveVisualizer):
    """Bokeh visualizer for a thermoelectric-cooler (TEC) action server.

    Subscribes to the action server's ``ws_live`` WebSocket and renders the
    object temperature, target object temperature, and output current
    (on a secondary y-axis) against time, alongside a latest-values table.
    The data columns track the controller's :data:`DEFAULT_QUERIES`. Common
    subscriber bring-up, widget callbacks, and the ingest loop are inherited
    from :class:`LiveVisualizer`.

    Attributes:
        data_dict_keys: ``datetime`` + ``DEFAULT_QUERIES`` column names.
        datasource: :class:`ColumnDataSource` backing the plot.
        datasource_table: :class:`ColumnDataSource` backing the table.
        layout: Composed Bokeh layout mounted on the document.
        input_max_points: Widget setting ``max_points``.
        input_update_rate: Widget setting ``update_rate``.
        plot: Bokeh ``figure`` with primary temperature axis and a
            secondary current axis.
        table: Bokeh ``DataTable`` showing the latest values.
    """

    SUBSCRIBE_LABEL = "TEC visualizer"
    Y_LABEL = "Temperature (C)"

    def _extend_plot(self):
        self.plot.extra_y_ranges = {"current_A": Range1d(start=-4.5, end=4.5)}
        self.plot.add_layout(
            LinearAxis(y_range_name="current_A", axis_label="Current (A)"), "right"
        )

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Wire up data sources, widgets, plot layout, and start the WS ingest task.

        Args:
            vis_serv: Host :class:`Vis` server providing the Bokeh document.
            serv_key: Configuration key of the TEC action server. If the
                server is not in the config, ``__init__`` returns early
                without registering any roots.
        """
        super().__init__(vis_serv, serv_key)
        if not self.connected:
            return

        self.data_dict_keys = ["datetime"] + DEFAULT_QUERIES
        self._build_panel()

        self._mount()
        self._add_plots()

    def add_points(self, datapackage_list: list):
        """Stream live TEC samples into the data source and table.

        Unpacks ``(value, epoch)`` tuples from each package, expands the
        ``tec_vals`` mapping into individual columns, streams the merged dict
        into ``self.datasource``, and refreshes the latest-values table.

        Args:
            datapackage_list: List of dicts from the live WebSocket.
        """
        latest_epoch = 0
        data_dict = {k: [] for k in self.data_dict_keys}
        for datapackage in datapackage_list:
            for datalab, (dataval, epochsec) in datapackage.items():
                if datalab == "tec_vals":
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

    def _add_plots(self):
        """Rebuild the figure with object/target temperatures and output current.

        Draws ``object_temperature`` (red solid), ``target_object_temperature``
        (red dotted), and ``output_current`` against the secondary current
        y-axis (blue solid).
        """
        # clear legend
        if self.plot.renderers:
            self.plot.legend.items = []

        # remove all old lines
        self.plot.renderers = []

        self.plot.line(
            x="datetime",
            y="object_temperature",
            line_color=SERIES[0],
            source=self.datasource,
            legend_label="object_temperature",
        )
        self.plot.line(
            x="datetime",
            y="target_object_temperature",
            line_color=SERIES[0],
            line_dash="dotted",
            source=self.datasource,
            legend_label="target_object_temperature",
        )
        self.plot.line(
            x="datetime",
            y="output_current",
            line_color=SERIES[1],
            source=self.datasource,
            legend_label="output_current",
            y_range_name="current_A",
        )
        self.plot.legend.border_line_alpha = 0.2
        self.plot.legend.background_fill_alpha = 0.2
