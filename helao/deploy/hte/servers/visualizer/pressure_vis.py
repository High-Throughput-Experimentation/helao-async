import time
import asyncio
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

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.core.servers.vis import Vis
from helao.helpers.ws_utils import WsSubscriber as Wss

FWIN = 20


class C_pressure:
    """Bokeh visualizer for analog pressure-sensor channels exposed by a Galil IO server.

    Subscribes to the action server's ``ws_live`` WebSocket and renders one
    raw and one rolling-mean trace per analog input channel listed under
    ``params.dev_ai``, alongside a latest-values data table.

    Attributes:
        vis: Host :class:`Vis` instance providing the Bokeh document.
        config_dict: ``params`` block from the visualizer's server config.
        update_rate: Minimum seconds between WebSocket polls.
        max_points: Rolling window length for the data source.
        last_update_time: Epoch timestamp of the most recent poll.
        live_key: Server key of the IO action server.
        wss: :class:`WsSubscriber` connected to ``ws_live``.
        data_url: Fully formed ``ws://`` URL for the live WebSocket.
        IOloop_data_run: Liveness flag for the data ingestion task.
        IOloop_stat_run: Liveness flag for the status ingestion task.
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
        IOtask: ``asyncio`` task running :meth:`IOloop_data`.
    """

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Wire up data sources, widgets, plot layout, and start the WS ingest task.

        Args:
            vis_serv: Host :class:`Vis` server providing the Bokeh document.
            serv_key: Configuration key of the pressure-sensor action server.
                If the server is not in the config, ``__init__`` returns
                early without registering any roots.
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
        psrv_host = psrv_config.get("host", None)
        psrv_port = psrv_config.get("port", None)
        self.wss = Wss(psrv_host, psrv_port, "ws_live")

        self.data_url = f"ws://{psrv_config['host']}:{psrv_config['port']}/ws_live"

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

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

    async def IOloop_data(self):
        """Continuously read the live WebSocket and schedule plot updates.

        Sleeps briefly each iteration, respects ``self.update_rate`` as a
        minimum gap between polls, and dispatches non-empty message batches
        to :meth:`add_points` on the document thread.
        """
        LOGGER.info(f" ... Pressure sensor visualizer subscribing to: {self.data_url}")
        while True:
            if time.time() - self.last_update_time >= self.update_rate:
                messages = await self.wss.read_messages()
                if messages:
                    self.vis.doc.add_next_tick_callback(
                        partial(self.add_points, messages)
                    )
                    self.last_update_time = time.time()
            await asyncio.sleep(0.01)

    def _add_plots(self):
        """Rebuild the pressure figure with raw and rolling-mean traces per channel."""
        # clear legend
        if self.plot.renderers:
            self.plot.legend.items = []

        # remove all old lines
        self.plot.renderers = []

        colors = ["red", "blue", "green", "orange", "purple", "cyan", "magenta"]
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
