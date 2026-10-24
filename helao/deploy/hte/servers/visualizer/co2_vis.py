from datetime import datetime

import numpy as np
import scipy.ndimage as ndi

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.ui.shared.palette import SERIES
from helao.ui.bokeh.vis import Vis
from ._live_panel import LivePanel
from helao.ui.bokeh.vis_subscriber import LiveVisualizer

FWIN = 20


class C_vis(LivePanel, LiveVisualizer):
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
    Y_LABEL = "CO2 (ppm)"

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

        self.data_dict_keys = ["datetime", "co2_ppm", "co2_ppm_mean"]
        self._build_panel()

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
            line_color=SERIES[0],
            legend_label="CO2 ppm (filtered)",
            source=self.datasource,
        )
        self.plot.line(
            x="datetime",
            y="co2_ppm_mean",
            line_color=SERIES[1],
            legend_label="CO2 ppm rolling mean",
            source=self.datasource,
        )
        self.plot.legend.border_line_alpha = 0.2
        self.plot.legend.background_fill_alpha = 0.2
