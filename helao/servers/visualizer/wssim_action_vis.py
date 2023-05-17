"""Action visualizer for the websocket simulator: WIP"""

import time
import websockets
import asyncio
import json
from datetime import datetime
from functools import partial
from copy import deepcopy

from bokeh.models import (
    TextInput,
)
from bokeh.models.widgets import Paragraph
from bokeh.plotting import figure
from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource, DatetimeTickFormatter

from helaocore.models.hlostatus import HloStatus
from helaocore.models.data import DataPackageModel
from helao.servers.vis import Vis
from helao.helpers.dispatcher import private_dispatcher


valid_data_status = (
    None,
    HloStatus.active,
)


class C_simactvis:
    """spectrometer visualizer module class"""

    def __init__(self, visServ: Vis, serv_key: str):
        self.vis = visServ
        self.config_dict = self.vis.server_cfg["params"]
        self.max_spectra = 5
        self.downsample = 2
        self.min_update_delay = 0.5  # drop plots if spectra come in too quickly

        self.ws_data_key = serv_key
        actserv_config = self.vis.world_cfg["servers"].get(self.ws_data_key, None)
        if actserv_config is None:
            return
        actserv_host = actserv_config.get("host", None)
        actserv_port = actserv_config.get("port", None)
        self.wss = Wss(actserv_host, actserv_port, "ws_data")

        self.data_url = (
            f"ws://{actserv_host}:{actserv_port}/ws_data"
        )

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

        self.data_dict_keys = ["datetime"] + [f"series_{i}" for i in range(6)]
        self.datasource = ColumnDataSource(data={k: [] for k in self.data_dict_keys})
        self.datasource_prev = ColumnDataSource(data=deepcopy(self.datasource.data))

        self.cur_action_uuid = ""
        self.prev_action_uuid = ""

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

        self.plot = figure(title="Title", height=300, width=500, output_backend="webgl")
        self.plot.xaxis.formatter = DatetimeTickFormatter(
            minsec='%T',
            minutes='%T',
            hourmin='%T',
            hours='%T',
        )
        self.plot.xaxis.axis_label = "Time (HH:MM:SS)"
        self.plot.yaxis.axis_label = "value"

        self.plot_prev = figure(title="Title", height=300, width=500, output_backend="webgl")
        self.plot_prev.xaxis.formatter = DatetimeTickFormatter(
            minsec='%T',
            minutes='%T',
            hourmin='%T',
            hours='%T',
        )
        self.plot_prev.xaxis.axis_label = "Time (HH:MM:SS)"
        self.plot_prev.yaxis.axis_label = "value"
        # combine all sublayouts into a single one
        docs_url = f"http://{host}:{port}/docs#/"
        server_link = f'<a href="{docs_url}" target="_blank">\'{self.live_key}\'</a>'
        headerbar = f"<b>Live vis module for server {server_link}</b>"
        self.layout = layout(
            [
                [
                    Spacer(width=20),
                    Div(
                        text=headerbar,
                        width=1004,
                        height=15,
                    ),
                ],
                [self.input_max_points, self.input_update_rate],
                Spacer(height=10),
                [self.plot, Spacer(width=20), self.plot_prev],
                Spacer(height=10),
            ],
            background="#C0C0C0",
            width=1024,
        )

        # to check if selection changed during ploting
        # self.xselect = self.xaxis_selector_group.active
        # self.yselect = self.yaxis_selector_group.active

        self._add_plots()

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)

    def cleanup_session(self, session_context):
        self.vis.print_message(f"'{self.ws_data_key}' Bokeh session closed", info=True)
        self.IOloop_data_run = False
        self.IOtask.cancel()

    def callback_input_max_points(self, attr, old, new, sender):
        """callback for input_max_points"""

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
        sender.value = value

    def callback_input_update_rate(self, attr, old, new, sender):
        """callback for input_update_rate"""

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

    async def IOloop_data(self):  # non-blocking coroutine, updates data source
        self.vis.print_message(" ... Live visualizer receiving messages.")
        while True:
            if time.time() - self.last_update_time >= self.update_rate:
                messages = await self.wss.read_messages()
                self.vis.doc.add_next_tick_callback(partial(self.add_points, messages))
                self.last_update_time = time.time()
            await asyncio.sleep(0.001)

    def add_points(self, datapackage_list: list):
        for datapackage in datapackage_list:
            # check if uuid has changed
            new_action_uuid = str(datapackage.action_uuid)
            if new_action_uuid != self.cur_action_uuid:
                self.vis.print_message(" ... reseting Spec graph")
                self.prev_action_uuid = self.cur_action_uuid
                self.cur_action_uuid = new_action_uuid

                # copy old data to "prev" plot
                self.datasource_prev.data = deepcopy(self.datasource.data)
                self.datasource.data = {k: [] for k in self.data_dict_keys}

            # update self.data_dict with incoming data package
            for _, data_dict in datapackage.datamodel.data.items():
                # unpack and sort epoch and channels
                epoch = data_dict["epoch_s"]
                dtstr = datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S.%f")
                ch_keys = sorted(
                    [k for k in data_dict.keys() if k.startswith("ch_")],
                    key=lambda x: int(x.split("_")[-1]),
                )
                ch_vals = [data_dict[k] for k in ch_keys]
                self.data_dict.update({dtstr: ch_vals[:: self.downsample]})

            # trim number of spectra being plotted
            if len(self.data_dict.keys()) > self.max_spectra:
                datetime_keys = sorted(self.data_dict.keys())
                delpts = len(self.data_dict.keys()) - self.max_spectra
                for key in datetime_keys[:delpts]:
                    self.data_dict.pop(key)

            self.datasource.data = self.data_dict
            self._add_plots()

    def _add_plots(self):
        # clear legend
        if self.plot.renderers:
            self.plot.legend.items = []

        if self.plot_prev.renderers:
            self.plot_prev.legend.items = []

        # remove all old lines
        self.plot.renderers = []
        self.plot_prev.renderers = []

        self.plot.title.text = f"active action_uuid: {self.cur_action_uuid}"
        self.plot_prev.title.text = f"previous action_uuid: {self.prev_action_uuid}"

        ds_keys = [x for x in sorted(self.datasource.data.keys()) if x != "wl"]
        for i, dt in enumerate(ds_keys):
            self.plot.line(
                x="wl",
                y=dt,
                line_color="blue" if i != len(ds_keys) - 1 else "red",
                source=self.datasource,
                name=self.cur_action_uuid,
                legend_label=dt,
            )

        dsp_keys = [x for x in sorted(self.datasource_prev.data.keys()) if x != "wl"]
        for i, dt in enumerate(dsp_keys):
            self.plot_prev.line(
                x="wl",
                y=dt,
                line_color="blue" if i != len(dsp_keys) - 1 else "red",
                source=self.datasource_prev,
                name=self.prev_action_uuid,
                legend_label=dt,
            )
