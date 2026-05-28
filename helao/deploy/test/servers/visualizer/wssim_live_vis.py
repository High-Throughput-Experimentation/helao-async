"""Bokeh visualizer module for the websocket simulator action server.

Subscribes to the simulator's ``ws_live`` websocket, plots the rolling
``series_<i>`` values against time, and mirrors the latest snapshot as a
two-column table.
"""

import time
import asyncio
from datetime import datetime
from functools import partial

from bokeh.models import (
    TextInput,
)
from bokeh.plotting import figure
from bokeh.models.widgets import Div
from bokeh.models.widgets import DataTable, TableColumn
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource, DatetimeTickFormatter

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.core.servers.vis import Vis
from helao.helpers.ws_utils import WsSubscriber as Wss


class C_simlivevis:
    """Live Bokeh visualizer for the websocket simulator action server.

    Builds widgets for ``max_points`` and ``update_rate``, a line plot of
    the synthetic series against time, and a key/value table for the
    latest sample. A background coroutine reads from the action server's
    ``ws_live`` websocket and streams the new points to both.

    Attributes:
        vis: Hosting visualizer server.
        update_rate: Polling period (seconds) between websocket reads.
        max_points: Rolling buffer size for the streamed plot.
        live_key: Name of the action server being visualized.
        wss: ``WsSubscriber`` consumer for ``ws_live`` messages.
        datasource: ``ColumnDataSource`` backing the line plot.
        datasource_table: ``ColumnDataSource`` backing the key/value table.
        layout: Top-level Bokeh layout.
    """

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Build the layout and start the polling coroutine.

        Args:
            vis_serv: Hosting visualizer server.
            serv_key: Name of the action server to visualize.
        """
        self.vis = vis_serv
        self.config_dict = self.vis.server_cfg.get("params", {})
        self.update_rate = self.config_dict.get("update_rate", 0.5)
        self.max_points = 500
        self.last_update_time = time.time()

        self.live_key = serv_key
        psrv_config = self.vis.world_cfg["servers"].get(self.live_key, None)
        if psrv_config is None:
            return
        host = psrv_config.get("host", None)
        port = psrv_config.get("port", None)
        self.wss = Wss(host, port, "ws_live")

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

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
        server_link = f'<a href="{docs_url}" target="_blank">\'{self.live_key}\'</a>'
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

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)
        self._add_plots()

    def cleanup_session(self, session_context):
        """Cancel the IO loop when the Bokeh session ends.

        Args:
            session_context: Bokeh session context (unused).
        """
        LOGGER.info(f"'{self.live_key}' Bokeh session closed")
        self.IOloop_data_run = False
        self.IOtask.cancel()

    def callback_input_max_points(self, attr, old, new, sender):
        """Validate and apply a new ``max_points`` input, then echo it back.

        Args:
            attr: Bokeh attribute name (unused).
            old: Previous string value.
            new: New string value.
            sender: The source widget.
        """

        def to_int(val):
            try:
                return int(val)
            except ValueError:
                return None

        newpts = to_int(new)
        oldpts = to_int(old)

        if newpts is None:
            if oldpts is not None:
                newpts = oldpts
            else:
                newpts = 500

        if newpts < 2:
            newpts = 2
        if newpts > 10000:
            newpts = 10000

        self.max_points = newpts

        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.max_points}")
        )

    def update_input_value(self, sender, value):
        """Push ``value`` back into the source widget.

        Args:
            sender: Bokeh widget to update.
            value: New value to assign.
        """
        sender.value = value

    def callback_input_update_rate(self, attr, old, new, sender):
        """Validate and apply a new update-rate input, then echo it back.

        Args:
            attr: Bokeh attribute name (unused).
            old: Previous string value.
            new: New string value.
            sender: The source widget.
        """

        def to_float(val):
            try:
                return float(val)
            except ValueError:
                return 0.5

        newpts = to_float(new)

        self.update_rate = newpts

        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.update_rate}")
        )

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

    async def IOloop_data(self):  # non-blocking coroutine, updates data source
        """Poll the live websocket and schedule UI updates on the document."""
        LOGGER.info(" ... Live visualizer receiving messages.")
        while True:
            if time.time() - self.last_update_time >= self.update_rate:
                messages = await self.wss.read_messages()
                self.vis.doc.add_next_tick_callback(partial(self.add_points, messages))
                self.last_update_time = time.time()
            await asyncio.sleep(0.01)

    def _add_plots(self):
        """Redraw the line plot, one renderer per non-time series."""
        # clear legend
        if self.plot.renderers:
            self.plot.legend.items = []

        # remove all old lines
        self.plot.renderers = []

        colors = ["red", "blue", "green", "orange"]
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
