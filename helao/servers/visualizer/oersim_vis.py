"""Action visualizer for the websocket simulator: WIP"""

import time
import asyncio
from functools import partial
from copy import deepcopy

from bokeh.models import (
    TextInput,
)
from bokeh.plotting import figure
from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource

from helao.helpers import logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

from helao.core.models.hlostatus import HloStatus
from helao.servers.vis import Vis
from helao.helpers.ws_subscriber import WsSubscriber as Wss


VALID_DATA_STATUS = (
    None,
    "active",
    HloStatus.active,
)

VALID_ACTION_NAME = ("measure_cp",)


class C_oersimvis:
    """spectrometer visualizer module class"""

    def __init__(self, vis_serv: Vis, serv_key: str):
        self.vis = vis_serv
        self.config_dict = self.vis.server_cfg.get("params", {})
        self.max_points = 500
        self.update_rate = 1e-3
        self.last_update_time = time.time()

        self.server_key = serv_key
        actserv_config = self.vis.world_cfg["servers"].get(self.server_key, None)
        if actserv_config is None:
            return
        actserv_host = actserv_config.get("host", None)
        actserv_port = actserv_config.get("port", None)
        self.wss = Wss(actserv_host, actserv_port, "ws_data")

        self.data_url = (
            f"ws://{actserv_config['host']}:{actserv_config['port']}/ws_data"
        )

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

        self.data_dict_keys = ["t_s", "erhe_v"]
        self.datasource = ColumnDataSource(
            data={key: [] for key in self.data_dict_keys}
        )
        self.cur_action_uuid = ""
        self.cur_comp = ""

        # prev_datasources aren't streamed, replot when axis or action_uuid changes
        self.prev_datasources = {}
        self.prev_action_uuid = ""
        self.prev_comp = ""
        self.prev_action_uuids = []

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

        self.plot = figure(title="Title", height=300, width=500)
        self.plot_prev = figure(title="Title", height=300, width=500)
        self.plot.xaxis.axis_label = "Time (seconds)"
        self.plot.yaxis.axis_label = "E vs RHE (V)"
        self.plot_prev.xaxis.axis_label = "Time (seconds)"
        self.plot_prev.yaxis.axis_label = "E vs RHE (V)"

        # combine all sublayouts into a single one
        docs_url = f"http://{actserv_host}:{actserv_port}/docs#/"
        server_link = f'<a href="{docs_url}" target="_blank">\'{self.server_key}\'</a>'
        headerbar = f"<b>OER CP simulator for server {server_link}</b>"
        self.layout = layout(
            [
                [Spacer(width=20), Div(text=headerbar, width=1004, height=15)],
                [
                    self.input_max_points,
                ],
                Spacer(height=10),
                [self.plot, Spacer(width=20), self.plot_prev],
                Spacer(height=10),
            ],
            background="#D6DBDF",
            width=1024,
        )

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)
        self.reset_plot(self.cur_action_uuid, forceupdate=True)

    def cleanup_session(self, session_context):
        LOGGER.info(f"'{self.server_key}' Bokeh session closed")
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

    async def IOloop_data(self):  # non-blocking coroutine, updates data source
        LOGGER.info(f" ... potentiostat visualizer subscribing to: {self.data_url}")
        while True:
            if time.time() - self.last_update_time >= self.update_rate:
                messages = await self.wss.read_messages()
                self.vis.doc.add_next_tick_callback(partial(self.add_points, messages))
                self.last_update_time = time.time()
            await asyncio.sleep(0.001)

    def add_points(self, datapackage_list: list):
        for data_package in datapackage_list:
            data_dict = {k: [] for k in self.data_dict_keys}
            if (
                data_package.datamodel.status in VALID_DATA_STATUS
                and data_package.action_name in VALID_ACTION_NAME
            ):
                # only resets if axis selector or action_uuid changes
                self.reset_plot(str(data_package.action_uuid))
                for _, uuid_dict in data_package.datamodel.data.items():
                    for data_label, data_val in uuid_dict.items():
                        if data_label in self.data_dict_keys:
                            if isinstance(data_val, list):
                                data_dict[data_label] += data_val
                            else:
                                data_dict[data_label].append(data_val)
                        elif data_label == "elements":
                            compstr = "-".join(
                                [
                                    f"{x}{y:.2f}"
                                    for x, y in zip(
                                        data_val, uuid_dict["atfracs"]
                                    )
                                ]
                            )
                            if self.cur_comp != compstr:
                                self.cur_comp = compstr
                                self._add_plots()

            # check for missing I_A in OCV
            max_len = max([len(v) for v in data_dict.values()])
            for k, v in data_dict.items():
                if len(v) < max_len:
                    pad_len = max_len - len(v)
                    data_dict[k] += ["NaN"] * pad_len
            self.datasource.stream(data_dict, rollover=self.max_points)

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
        colors = ["red", "blue", "orange", "green"]
        self.plot.line(
            x="t_s",
            y="erhe_v",
            line_color=colors[0],
            source=self.datasource,
            name=self.cur_action_uuid,
            legend_label=self.cur_comp,
        )
        self.plot.legend.location = "bottom_right"
        for puuid in self.prev_action_uuids:
            self.plot_prev.line(
                x="t_s",
                y="erhe_v",
                line_color=colors[1],
                source=self.prev_datasources[puuid],
                name=puuid,
                legend_label=self.prev_comp,
            )
            self.plot_prev.legend.location = "bottom_right"

    def reset_plot(self, new_action_uuid=None, forceupdate: bool = False):
        if self.cur_action_uuid != new_action_uuid or forceupdate:
            if new_action_uuid is not None:
                LOGGER.info(" ... reseting CP graph")
                self.prev_action_uuid = self.cur_action_uuid
                self.prev_comp = self.cur_comp
                if self.prev_action_uuid != "":
                    self.prev_action_uuids.append(self.prev_action_uuid)
                    LOGGER.info(f"previous uuids: {self.prev_action_uuids}")
                    # copy old data to "prev" plot
                    self.prev_datasources[self.prev_action_uuid] = ColumnDataSource(
                        data=deepcopy(self.datasource.data)
                    )
                self.cur_action_uuid = new_action_uuid
                # update prev_datasources
                while len(self.prev_action_uuids) > 1:
                    rp = self.prev_action_uuids.pop(0)
                    self.prev_datasources.pop(rp)
                self.datasource.data = {key: [] for key in self.data_dict_keys}
            self._add_plots()
