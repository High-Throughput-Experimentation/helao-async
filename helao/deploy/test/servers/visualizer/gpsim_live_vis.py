"""Bokeh visualizer module for the GP-simulator live data stream.

Subscribes to the GP simulator's ``ws_live`` websocket and renders the
running acquisition table together with predicted-vs-acquired histograms
per plate.
"""

from functools import partial

from bokeh.models import (
    TextInput,
)
from bokeh.plotting import figure
from bokeh.models.widgets import Div
from bokeh.models.widgets import DataTable, TableColumn
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource
from bokeh.models.widgets import Toggle
import numpy as np

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.framework.app.vis import Vis
from helao.framework.adapters.vis_subscriber import LiveVisualizer


class C_vis(LiveVisualizer):
    """Live Bokeh visualizer for the GP-simulator action server.

    Builds a layout with an update-rate input, a status toggle, a
    predicted-vs-ground-truth histogram plot, and a recent-acquisitions
    table. Common subscriber bring-up, the ``update sec`` callback, and the
    ingest loop are inherited from :class:`LiveVisualizer`.

    Attributes:
        datasource_table: ``ColumnDataSource`` backing the table.
        hists: Per-plate cached histogram quads (predicted/ground truth).
        layout: Top-level Bokeh layout.
    """

    SUBSCRIBE_LABEL = "Live visualizer"

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Set up subscriber, widgets, plot, and table; start the IO loop.

        Args:
            vis_serv: Hosting visualizer server.
            serv_key: Name of the action server to visualize.
        """
        super().__init__(vis_serv, serv_key)
        if not self.connected:
            return
        host = self.host
        port = self.port

        self.data_dict_keys = [
            "plate_id",
            "step",
            "frac_acquired",
            "last_acquisition",
            "orchestrator",
        ]
        self.hist_keys = ["pred_avail", "gt_acquired"]
        self.hists = {}

        self.datasource_table = ColumnDataSource(
            data={k: [] for k in self.data_dict_keys}
        )

        # create visual elements
        self.layout = []

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

        self.plot = figure(height=300, width=880, output_backend="webgl")
        self.plot.xaxis.axis_label = "Eta (V vs O2/H2O)"
        self.plot.yaxis.axis_label = "density"

        self.status_button = Toggle(
            label="Disabled",
            disabled=True,
            button_type="success",
            width=400,
        )  # success: green, danger: red

        self.table = DataTable(
            source=self.datasource_table,
            columns=[
                TableColumn(field="plate_id", title="plate_id"),
                TableColumn(field="step", title="acqusition number per plate"),
                TableColumn(
                    field="frac_acquired", title="fraction of compositions acquired"
                ),
                TableColumn(
                    field="last_acquisition", title="last acquired composition"
                ),
                TableColumn(field="orchestrator", title="requested by"),
            ],
            height=200,
            width=880,
            index_width=20,
        )
        # combine all sublayouts into a single one
        docs_url = f"http://{host}:{port}/docs#/"
        server_link = f'<a href="{docs_url}" target="_blank">\'{self.serv_key}\'</a>'
        headerbar = f"<b>Live vis module for server {server_link}</b>"
        tableheader = f"<b>Last 20 acquisitions across all Orchestrators:</b>"
        self.layout = layout(
            [
                Spacer(width=20),
                [Div(text=headerbar, width=1004, height=15)],
                [
                    Spacer(width=10),
                    self.input_update_rate,
                    Spacer(width=10),
                    self.status_button,
                ],
                Spacer(height=10),
                [Spacer(width=10), self.plot, Spacer(width=10)],
                Spacer(height=10),
                [Div(text=tableheader, width=1004, height=15)],
                [Spacer(width=10), self.table, Spacer(width=10)],
            ],
            background="#D6DBDF",
            width=1024,
        )

        self._mount()
        self._add_plots()

    def add_points(self, datapackage_list: list):
        """Stream a batch of websocket messages into the table and histograms.

        Updates the status toggle, recomputes per-plate predicted and
        acquired histograms, streams new rows to the table, and refreshes
        the plot.

        Args:
            datapackage_list: List of message dicts from the websocket.
        """
        latest_epoch = 0
        data_dict = {}
        hist_dict = {}
        for datapackage in datapackage_list:
            for datalab, (dataval, epochsec) in datapackage.items():
                if datalab in self.data_dict_keys:
                    data_dict[datalab] = (
                        dataval
                        if datalab != "frac_acquired"
                        else [round(x, 4) for x in dataval]
                    )
                elif datalab in self.hist_keys:
                    hist_dict[datalab] = dataval
                elif datalab == "status":
                    if isinstance(dataval, list):
                        dataval = dataval[0]
                    self.status_button.label = dataval
                    if "was advised" in dataval:
                        self.status_button.button_type = "danger"
                    else:
                        self.status_button.button_type = "success"
                latest_epoch = max([epochsec, latest_epoch])

        histquads = []
        if "plate_id" in data_dict:
            for i in range(len(data_dict["plate_id"])):
                pnum = len(hist_dict["pred_avail"][i])
                print(
                    "pred range:",
                    min(hist_dict["pred_avail"][i]),
                    max(hist_dict["pred_avail"][i]),
                )
                phist, pedge = np.histogram(
                    hist_dict["pred_avail"][i], bins=100, range=(0.2, 0.7), density=True
                )
                gnum = len(hist_dict["gt_acquired"][i])
                print(
                    "gt range:",
                    min(hist_dict["gt_acquired"][i]),
                    max(hist_dict["gt_acquired"][i]),
                )
                ghist, gedge = np.histogram(
                    hist_dict["gt_acquired"][i],
                    bins=100,
                    range=(0.2, 0.7),
                    density=True,
                )
                histquads = (phist, pedge, pnum, ghist, gedge, gnum)
                self.hists[data_dict["plate_id"][i]] = histquads

        if latest_epoch != 0 and histquads and data_dict:
            self.datasource_table.stream(data_dict, rollover=20)
            self._add_plots()

    def _add_plots(self):
        """Redraw the histogram plot from the cached per-plate quads."""
        # clear legend
        if self.plot.renderers:
            self.plot.legend.items = []

        # remove all old lines
        self.plot.renderers = []

        colors = ["red", "blue", "green", "orange"]
        for i, (k, (phist, pedge, pnum, ghist, gedge, gnum)) in enumerate(
            self.hists.items()
        ):
            self.plot.quad(
                top=phist,
                bottom=0,
                left=pedge[:-1],
                right=pedge[1:],
                line_color=colors[i],
                fill_color=None,
                alpha=1.0,
                legend_label=f"{k} predicted available n={pnum:d}",
            )
            self.plot.quad(
                top=ghist,
                bottom=0,
                left=gedge[:-1],
                right=gedge[1:],
                line_color=None,
                fill_color=colors[i],
                alpha=0.3,
                legend_label=f"{k} g.t. acquired n={gnum:d}",
            )
            self.plot.legend.border_line_alpha = 0.2
            self.plot.legend.background_fill_alpha = 0.2
