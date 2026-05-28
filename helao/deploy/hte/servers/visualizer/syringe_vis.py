"""Bokeh live visualizer for a syringe-pump action server.

Exposes :class:`C_syringe`, a work-in-progress visualizer that subscribes to
the server's ``ws_live`` WebSocket and renders a single time-series plot
together with a latest-values data table.
"""

import time
import asyncio
from datetime import datetime
from functools import partial

from bokeh.models import TextInput
from bokeh.plotting import figure
from bokeh.models.widgets import Div
from bokeh.models.widgets import DataTable, TableColumn
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource, DatetimeTickFormatter

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.core.servers.vis import Vis
from helao.helpers.ws_utils import WsSubscriber as Wss


class C_syringe:
    """Bokeh visualizer for a syringe-pump action server.

    Subscribes to the action server's ``ws_live`` WebSocket and renders a
    single time-series figure alongside a latest-values table.

    Attributes:
        vis: Host :class:`Vis` instance providing the Bokeh document.
        config_dict: ``params`` block from the visualizer's server config.
        update_rate: Minimum seconds between WebSocket polls.
        max_points: Rolling window length for the data source.
        last_update_time: Epoch timestamp of the most recent poll.
        live_key: Server key of the syringe pump action server.
        wss: :class:`WsSubscriber` connected to ``ws_live``.
        data_url: Fully formed ``ws://`` URL for the live WebSocket.
        IOloop_data_run: Liveness flag for the data ingestion task.
        IOloop_stat_run: Liveness flag for the status ingestion task.
        data_dict_keys: Column names streamed into the plot source.
        datasource: :class:`ColumnDataSource` backing the time-series plot.
        datasource_table: :class:`ColumnDataSource` backing the latest-values table.
        layout: Composed Bokeh layout mounted on the document.
        input_max_points: Widget setting ``max_points``.
        input_update_rate: Widget setting ``update_rate``.
        plot: Bokeh ``figure`` for the live trace.
        table: Bokeh ``DataTable`` showing the most recent values.
        IOtask: ``asyncio`` task running :meth:`IOloop_data`.
    """

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Wire up data sources, widgets, plot layout, and start the WS ingest task.

        Args:
            vis_serv: Host :class:`Vis` server providing the Bokeh document.
            serv_key: Configuration key of the syringe-pump action server.
                If the server is not in the config, ``__init__`` returns
                early without registering any roots.
        """
        self.vis = vis_serv
        self.config_dict = self.vis.server_cfg.get("params", {})
        self.update_rate = self.config_dict.get("update_rate", 0.5)
        self.max_points = 500
        self.last_update_time = time.time()

        self.live_key = serv_key
        syringeserv_config = self.vis.world_cfg["servers"].get(self.live_key, None)
        if syringeserv_config is None:
            return
        syringeserv_host = syringeserv_config.get("host", None)
        syringeserv_port = syringeserv_config.get("port", None)
        self.wss = Wss(syringeserv_host, syringeserv_port, "ws_live")

        self.data_url = (
            f"ws://{syringeserv_config['host']}:{syringeserv_config['port']}/ws_live"
        )

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

        self.data_dict_keys = ["datetime", "co2_ppm"]

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
        docs_url = f"http://{syringeserv_host}:{syringeserv_port}/docs#/"
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

    def cleanup_session(self, session_context):
        """Cancel the data ingest task when the Bokeh session is torn down.

        Args:
            session_context: Bokeh session context (unused).
        """
        LOGGER.info(f"'{self.live_key}' Bokeh session closed")
        self.IOloop_data_run = False
        self.IOtask.cancel()

    def callback_input_max_points(self, attr, old, new, sender):
        """Validate the ``max datapoints`` input and update the rolling window.

        Parses ``new`` as an int, falls back to ``old`` (or ``500``) on bad
        input, then clamps to ``[2, 10000]`` before storing it as
        ``self.max_points`` and refreshing the widget.

        Args:
            attr: Bokeh property name that changed.
            old: Prior text value.
            new: New text value typed by the user.
            sender: The :class:`TextInput` to refresh.
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
        """Write ``value`` back onto a Bokeh input widget on the document thread.

        Args:
            sender: Bokeh input widget whose ``value`` is being updated.
            value: New string value to assign.
        """
        sender.value = value

    def callback_input_update_rate(self, attr, old, new, sender):
        """Validate the ``update sec`` input and adjust the polling cadence.

        Parses ``new`` as a float (defaulting to ``0.5`` on bad input), stores
        it as ``self.update_rate``, and writes the value back to the widget.

        Args:
            attr: Bokeh property name that changed.
            old: Prior text value.
            new: New text value typed by the user.
            sender: The :class:`TextInput` to refresh.
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
        """Stream live samples into the data source and refresh the table.

        Unpacks ``(value, epoch)`` tuples from each package, expands
        ``sim_dict`` payloads, and rebuilds the plot renderers.

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
        self._add_plots()

    async def IOloop_data(self):
        """Continuously pull WebSocket data packages and schedule plot updates.

        Runs for the lifetime of the Bokeh session and honors
        ``self.update_rate`` as a minimum gap between polls.
        """
        LOGGER.info(f" ... CO2 sensor visualizer subscribing to: {self.data_url}")
        while True:
            if time.time() - self.last_update_time >= self.update_rate:
                messages = await self.wss.read_messages()
                self.vis.doc.add_next_tick_callback(partial(self.add_points, messages))
                self.last_update_time = time.time()
            await asyncio.sleep(0.01)

    def _add_plots(self):
        """Rebuild the figure with a single ``co2_ppm`` trace against time."""
        # clear legend
        if self.plot.renderers:
            self.plot.legend.items = []

        # remove all old lines
        self.plot.renderers = []

        self.plot.line(
            x="datetime",
            y="co2_ppm",
            line_color="red",
            source=self.datasource,
        )

    def reset_plot(self, forceupdate: bool = False):
        """Rebuild the figure renderers.

        Args:
            forceupdate: Accepted for parity with other visualizers; the plot
                is always rebuilt.
        """
        self._add_plots()
