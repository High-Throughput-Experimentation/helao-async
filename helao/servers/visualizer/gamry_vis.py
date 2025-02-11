import time
import asyncio
from functools import partial
from copy import deepcopy

from bokeh.models import (
    RadioButtonGroup,
    TextInput,
)
from bokeh.models.widgets import Paragraph
from bokeh.plotting import figure
from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource
from bokeh.models import Button
from bokeh.events import ButtonClick

from helao.helpers import logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

from helao.core.models.hlostatus import HloStatus
from helao.helpers.premodels import Action
from helao.servers.vis import Vis
from helao.helpers.ws_subscriber import WsSubscriber as Wss
from helao.helpers.dispatcher import async_private_dispatcher

VALID_DATA_STATUS = (
    None,
    "active",
    HloStatus.active,
)

AXIS_MAP = {
    "run_CA": ("t_s", "I_A"),
    "run_CP": ("t_s", "Ewe_V"),
    "run_CV": ("Ewe_V", "I_A"),
    "run_OCV": ("t_s", "Ewe_V"),
    "run_RCA": ("t_s", "I_A"),
    "run_LSV": ("Ewe_V", "I_A"),
    # "run_EIS": ("Re_Z", "Im_Z"),
}

VALID_ACTION_NAME = [k for k in AXIS_MAP.keys()]


class C_potvis:
    """potentiostat visualizer module class"""

    def __init__(self, vis_serv: Vis, serv_key: str):
        self.vis = vis_serv
        self.config_dict = self.vis.server_cfg.get("params", {})
        self.max_points = 5000
        self.max_prev = 4
        self.update_rate = 1e-3
        self.last_update_time = time.time()

        self.potentiostat_key = serv_key
        self.potserv_config = self.vis.world_cfg["servers"].get(self.potentiostat_key, None)
        if self.potserv_config is None:
            return
        self.potserv_host = self.potserv_config.get("host", None)
        self.potserv_port = self.potserv_config.get("port", None)
        self.wss = Wss(self.potserv_host, self.potserv_port, "ws_data")

        self.data_url = (
            f"ws://{self.potserv_config['host']}:{self.potserv_config['port']}/ws_data"
        )

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

        self.data_dict_keys = ["t_s", "Ewe_V", "Ach_V", "I_A"]
        self.datasource = ColumnDataSource(
            data={key: [] for key in self.data_dict_keys}
        )
        self.cur_action_uuid = ""

        # prev_datasources aren't streamed, replot when axis or action_uuid changes
        self.prev_datasources = {}
        self.prev_action_uuid = ""
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

        self.input_max_prev = TextInput(
            value=f"{self.max_prev}",
            title="max previous plots",
            disabled=False,
            width=150,
            height=40,
        )
        self.input_max_prev.on_change(
            "value",
            partial(self.callback_input_max_prev, sender=self.input_max_prev),
        )

        self.button_stop_measure = Button(
            label="Stop measurement",
            button_type="danger",
            width=70,
            align="end",
        )
        self.button_stop_measure.on_event(ButtonClick, self.callback_stop_measure)

        self.xaxis_selector_group = RadioButtonGroup(
            labels=self.data_dict_keys, active=0, width=500
        )
        self.yaxis_selector_group = RadioButtonGroup(
            labels=self.data_dict_keys, active=3, width=500
        )
        self.xaxis_selector_group.on_change(
            "active", partial(self.callback_selector_change)
        )
        self.yaxis_selector_group.on_change(
            "active", partial(self.callback_selector_change)
        )

        self.plot = figure(title="Title", height=300, width=500)
        self.plot_prev = figure(title="Title", height=300, width=500)

        # combine all sublayouts into a single one
        docs_url = f"http://{self.potserv_host}:{self.potserv_port}/docs#/"
        server_link = (
            f'<a href="{docs_url}" target="_blank">\'{self.potentiostat_key}\'</a>'
        )
        headerbar = f"<b>Potentiostat Visualizer module for server {server_link}</b>"
        self.layout = layout(
            [
                [Spacer(width=20), Div(text=headerbar, width=1004, height=15)],
                [
                    self.input_max_points,
                    Spacer(width=20),
                    self.input_max_prev,
                    Spacer(width=20),
                    self.button_stop_measure,
                ],
                [
                    Paragraph(text="""x-axis:""", width=500, height=15),
                    Paragraph(text="""y-axis:""", width=500, height=15),
                ],
                [self.xaxis_selector_group, self.yaxis_selector_group],
                Spacer(height=10),
                [self.plot, Spacer(width=20), self.plot_prev],
                Spacer(height=10),
            ],
            background="#D6DBDF",
            width=1024,
        )

        # to check if selection changed during ploting
        self.xselect = self.xaxis_selector_group.active
        self.yselect = self.yaxis_selector_group.active

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)
        self.reset_plot(self.cur_action_uuid, forceupdate=True)

    def callback_stop_measure(self, event):
        LOGGER.info("stopping gamry measurement")
        self.vis.doc.add_next_tick_callback(
            partial(
                async_private_dispatcher,
                server_key=self.potentiostat_key,
                host=self.potserv_host,
                port=self.potserv_port,
                private_action="stop_private",
                params_dict={},
                json_dict={},
            )
        )

    def cleanup_session(self, session_context):
        LOGGER.info(f"'{self.potentiostat_key}' Bokeh session closed")
        self.IOloop_data_run = False
        self.IOtask.cancel()

    def callback_selector_change(self, attr, old, new):
        self.reset_plot()

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

    def callback_input_max_prev(self, attr, old, new, sender):
        """callback for input_max_prev"""

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
                newpts = 4

        self.max_prev = newpts

        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.max_prev}")
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
            await asyncio.sleep(0.01)

    def add_points(self, datapackage_list: list):
        for data_package in datapackage_list:
            data_dict = {k: [] for k in self.data_dict_keys}
            if (
                data_package.datamodel.status in VALID_DATA_STATUS
                and data_package.action_name in VALID_ACTION_NAME
            ):
                # only resets if axis selector or action_uuid changes
                self.reset_plot(data_package.action_uuid)
                for _, uuid_dict in data_package.datamodel.data.items():
                    for data_label, data_val in uuid_dict.items():
                        if data_label in self.data_dict_keys:
                            if isinstance(data_val, list):
                                data_dict[data_label] += data_val
                            else:
                                data_dict[data_label].append(data_val)

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
        self.plot_prev.title.text = f"last {len(self.prev_action_uuids)} actions"
        xstr = self.data_dict_keys[self.xselect]
        ystr = self.data_dict_keys[self.yselect]
        LOGGER.info(f"{xstr}, {ystr}")
        colors = ["red", "blue", "orange", "green"]
        self.plot.line(
            x=xstr,
            y=ystr,
            line_color=colors[0],
            source=self.datasource,
            name=self.cur_action_uuid,
            legend_label=ystr,
        )
        for i, puuid in enumerate(self.prev_action_uuids):
            self.plot_prev.line(
                x=xstr,
                y=ystr,
                line_color=colors[i % len(colors)],
                source=self.prev_datasources[puuid],
                name=puuid,
                # legend_label=puuid.split("-")[0],
                legend_label=f"{i+1}",
            )

    def reset_plot(self, new_data_package=None, forceupdate: bool = False):
        new_action_uuid = ""
        action_name = ""
        if new_data_package is not None:
            new_action_uuid = str(new_data_package.action_uuid)
            action_name = new_data_package.action_name
        if self.cur_action_uuid != new_action_uuid or forceupdate:
            LOGGER.info(" ... reseting Gamry graph")
            self.prev_action_uuid = self.cur_action_uuid
            if self.prev_action_uuid != "":
                self.prev_action_uuids.append(self.prev_action_uuid)
                LOGGER.info(f"previous uuids: {self.prev_action_uuids}")
                # copy old data to "prev" plot
                self.prev_datasources[self.prev_action_uuid] = ColumnDataSource(
                    data=deepcopy(self.datasource.data)
                )
            self.cur_action_uuid = new_action_uuid
            # update prev_datasources
            while len(self.prev_action_uuids) > self.max_prev:
                rp = self.prev_action_uuids.pop(0)
                self.prev_datasources.pop(rp)
            self.datasource.data = {key: [] for key in self.data_dict_keys}
            if action_name in AXIS_MAP:
                xlab, ylab = AXIS_MAP[action_name]
                self.xaxis_selector_group.update(active=self.data_dict_keys.index(xlab))
                self.yaxis_selector_group.update(active=self.data_dict_keys.index(ylab))
                self.xselect = self.xaxis_selector_group.active
                self.yselect = self.yaxis_selector_group.active
            self._add_plots()
        if (self.xselect != self.xaxis_selector_group.active) or (
            self.yselect != self.yaxis_selector_group.active
        ):
            self.xselect = self.xaxis_selector_group.active
            self.yselect = self.yaxis_selector_group.active
            self._add_plots()
