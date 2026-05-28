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


class C_mfc:
    """Bokeh visualizer for a multi-device mass flow controller server.

    Subscribes to the action server's ``ws_live`` WebSocket and renders per
    device traces for the currently selected control variable (mass flow or
    pressure) together with a setpoint reference and a rolling mean. A
    side-by-side data table summarises the latest sample. The y-axis label
    and active variable switch automatically when the device's
    ``control_point`` reports a different control mode.

    Attributes:
        vis: Host :class:`Vis` instance providing the Bokeh document.
        actsrv_cfg: ``params`` block from the MFC action server's config.
        config_dict: ``params`` block from the visualizer's server config.
        update_rate: Minimum seconds between WebSocket polls.
        max_points: Rolling window length for the data source.
        last_update_time: Epoch timestamp of the most recent poll.
        live_key: Server key of the MFC action server.
        wss: :class:`WsSubscriber` connected to ``ws_live``.
        data_url: Fully formed ``ws://`` URL for the live WebSocket.
        IOloop_data_run: Liveness flag for the data ingestion task.
        IOloop_stat_run: Liveness flag for the status ingestion task.
        data_suffices: Per-device measurement field suffixes.
        data_dict_keys: Combined ``datetime`` + per-device columns.
        devices: Sorted list of device names from the action server.
        datasource: :class:`ColumnDataSource` backing the plot.
        datasource_table: :class:`ColumnDataSource` backing the table.
        layout: Composed Bokeh layout mounted on the document.
        input_max_points: Widget setting ``max_points``.
        input_update_rate: Widget setting ``update_rate``.
        plot: Bokeh ``figure`` for the live trace.
        table: Bokeh ``DataTable`` showing the latest values.
        control_mode: Last observed device ``control_point`` value.
        yvar: Currently plotted variable (``"mass_flow"`` or ``"pressure"``).
        IOtask: ``asyncio`` task running :meth:`IOloop_data`.
    """

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Wire up data sources, widgets, plot layout, and start the WS ingest task.

        Args:
            vis_serv: Host :class:`Vis` server providing the Bokeh document.
            serv_key: Configuration key of the MFC action server to subscribe
                to. If the server is not in the config, ``__init__`` returns
                early without registering any roots.
        """
        self.vis = vis_serv
        self.actsrv_cfg = self.vis.world_cfg["servers"][serv_key]["params"]
        self.config_dict = self.vis.server_cfg.get("params", {})
        self.update_rate = self.config_dict.get("update_rate", 0.5)
        self.max_points = 500
        self.last_update_time = time.time()

        self.live_key = serv_key
        tserv_config = self.vis.world_cfg["servers"].get(self.live_key, None)
        if tserv_config is None:
            return
        tserv_host = tserv_config.get("host", None)
        tserv_port = tserv_config.get("port", None)
        self.wss = Wss(tserv_host, tserv_port, "ws_live")

        self.data_url = f"ws://{tserv_config['host']}:{tserv_config['port']}/ws_live"

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

        self.data_suffices = [
            # "epoch_s",
            "setpoint",
            "control_point",
            "gas",
            "mass_flow",
            "mass_flow_mean",
            "pressure",
            "pressure_mean",
            "temperature",
            # "total_flow",
            "volumetric_flow",
            "hold_valve",
            "lock_display",
            "acquire_time",
            # "time_now",
        ]

        self.data_dict_keys = ["datetime"]
        self.devices = sorted(self.actsrv_cfg["devices"].keys())
        for device_name in self.devices:
            for suffix in self.data_suffices:
                self.data_dict_keys.append(f"{device_name}__{suffix}")
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
        self.plot.yaxis.axis_label = "Flow rate (sccm)"

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
        docs_url = f"http://{tserv_host}:{tserv_port}/docs#/"
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
        self.control_mode = "mass flow"
        self.yvar = "mass_flow"

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
        """Stream live MFC samples into the data source and switch axes on mode change.

        Expands nested per-device dicts into flat ``device__suffix`` columns,
        computes rolling means for ``pressure`` and ``mass_flow`` columns,
        detects ``control_point`` changes (switching between mass-flow and
        pressure plotting), and refreshes the data table.

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
                elif isinstance(dataval, dict):
                    for k, v in dataval.items():
                        data_dict[f"{datalab}__{k}"].append(v)
                elif isinstance(dataval, list):
                    data_dict[datalab] += dataval
                else:
                    data_dict[datalab].append(dataval)
                latest_epoch = max([epochsec, latest_epoch])
            data_dict["datetime"].append(datetime.fromtimestamp(latest_epoch))
        for mvar in self.data_dict_keys:
            if mvar.endswith("pressure") or mvar.endswith("mass_flow"):
                try:
                    mvec = np.concatenate((self.datasource.data[mvar], data_dict[mvar]))
                    if len(mvec) >= FWIN:
                        data_dict[f"{mvar}_mean"] = list(
                            ndi.uniform_filter1d(mvec, FWIN, mode="nearest")[
                                -len(data_dict[mvar]) :
                            ]
                        )
                    else:
                        data_dict[f"{mvar}_mean"] = data_dict[mvar]
                except Exception:
                    LOGGER.error(f"Error processing {mvar}", exc_info=True)
                    LOGGER.info(f"datasource {self.datasource.data[mvar]}")
                    LOGGER.info(f"data_dict {self.data_dict[mvar]}")
                    data_dict[f"{mvar}_mean"] = data_dict[mvar]

        for dev_name in self.devices:
            control_modes = data_dict[f"{dev_name}__control_point"]
            if control_modes:
                control_mode = data_dict[f"{dev_name}__control_point"][-1].strip()
                if self.control_mode != control_mode:
                    if control_mode == "mass flow":
                        self.yvar = "mass_flow"
                        self.plot.yaxis.axis_label = "Flow rate (sccm)"
                    else:
                        self.yvar = "pressure"
                        self.plot.yaxis.axis_label = "Pressure (psia)"
                    self.datasource.data = {k: [] for k in self.data_dict_keys}

        self.datasource.stream(data_dict, rollover=self.max_points)
        keys = list(data_dict.keys())
        values = [data_dict[k][-1] for k in keys]
        table_data_dict = {"name": keys, "value": values}
        self.datasource_table.stream(table_data_dict, rollover=len(keys))
        if not self.plot.renderers or self.control_mode != control_mode:
            LOGGER.info(f"{self.control_mode} changed to {control_mode}")
            self.control_mode = control_mode
            self._add_plots()

    async def IOloop_data(self):
        """Continuously read the live WebSocket and schedule plot updates.

        Sleeps briefly each iteration, respects ``self.update_rate`` as a
        minimum gap between polls, and dispatches non-empty message batches
        to :meth:`add_points` on the document thread.
        """
        LOGGER.info(
            f" ... Mass flow controller visualizer subscribing to: {self.data_url}"
        )
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
        """Rebuild the flow/pressure figure with one trace group per device.

        For each device draws an actual line, a dotted setpoint line, and a
        blue rolling-mean line, using the currently selected ``yvar``
        (mass flow or pressure).
        """
        # clear legend
        if self.plot.renderers:
            self.plot.legend.items = []

        # remove all old lines
        self.plot.renderers = []

        colors = ["red", "green", "orange", "purple", "cyan", "magenta"]
        for dev_name, color in zip(self.devices, colors[: len(self.devices)]):
            self.plot.line(
                x="datetime",
                y=f"{dev_name}__{self.yvar}",
                line_color=color,
                line_dash="solid",
                source=self.datasource,
                legend_label=f"{dev_name} actual",
            )
            self.plot.line(
                x="datetime",
                y=f"{dev_name}__setpoint",
                line_color=color,
                line_dash="dotted",
                source=self.datasource,
                legend_label=f"{dev_name} setpoint",
            )
            self.plot.line(
                x="datetime",
                y=f"{dev_name}__{self.yvar}_mean",
                line_color="blue",
                line_dash="solid",
                source=self.datasource,
                legend_label=f"{dev_name} rolling mean",
            )
        self.plot.legend.border_line_alpha = 0.2
        self.plot.legend.background_fill_alpha = 0.2

    def reset_plot(self, forceupdate: bool = False):
        """Rebuild the figure renderers.

        Args:
            forceupdate: Accepted for parity with other visualizers; the plot
                is always rebuilt.
        """
        # self.xselect = self.xaxis_selector_group.active
        # self.yselect = self.yaxis_selector_group.active
        self._add_plots()
