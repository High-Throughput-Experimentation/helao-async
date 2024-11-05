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
from helaocore.models.hlostatus import HloStatus
from helao.helpers.premodels import Action
from helao.servers.vis import Vis
from helao.helpers.ws_subscriber import WsSubscriber as Wss
from helao.helpers.dispatcher import async_private_dispatcher

VALID_DATA_STATUS = (
    None,
    "active",
    HloStatus.active,
)

VALID_ACTION_NAME = (
    "run_CA",
    "run_CP",
    "run_CV",
    "run_OCV",
)


class C_biovis:
    """potentiostat visualizer module class"""

    def __init__(self, vis_serv: Vis, serv_key: str):
        self.vis = vis_serv
        self.config_dict = self.vis.server_cfg.get("params", {})
        self.num_channels = self.config_dict.get("num_channels", 1)
        self.max_points = 500
        self.update_rate = 1e-3
        self.last_update_time = time.time()

        self.potentiostat_key = serv_key
        self.potserv_config = self.vis.world_cfg["servers"].get(
            self.potentiostat_key, None
        )
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

        self.data_dict_keys = ["t_s", "Ewe_V", "I_A", "P_W", "cycle"]

        # separate data sources for each channel
        self.channel_datasources = {
            ch: ColumnDataSource(data={key: [] for key in self.data_dict_keys})
            for ch in range(self.num_channels)
        }
        self.channel_datasources_prev = {
            ch: ColumnDataSource(data={key: [] for key in self.data_dict_keys})
            for ch in range(self.num_channels)
        }
        self.channel_action_uuid = {ch: "" for ch in range(self.num_channels)}
        self.channel_action_uuid_prev = {ch: "" for ch in range(self.num_channels)}

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

        self.channel_plots = [
            figure(title=f"channel {ch}", height=300, width=500)
            for ch in range(self.num_channels)
        ]

        self.channel_plots_prev = [
            figure(title=f"channel {ch}", height=300, width=500)
            for ch in range(self.num_channels)
        ]

        # generate 2-column layout for potentiostat channels
        self.vert_groups = [
            [
                item
                for horiz_group in [
                    (plot, Spacer(width=20), plot_prev)
                    for plot, plot_prev in zip(
                        self.channel_plots,
                        self.channel_plots_prev,
                    )
                ]
                for item in horiz_group
            ]
            for i in range(self.num_channels)
        ]
        self.plot_divs = [
            vert_item
            for vert_group in zip(
                self.vert_groups, [Spacer(height=10)] * len(self.vert_groups)
            )
            for vert_item in vert_group
        ]

        # combine all sublayouts into a single one
        docs_url = f"http://{self.potserv_host}:{self.potserv_port}/docs#/"
        server_link = (
            f'<a href="{docs_url}" target="_blank">\'{self.potentiostat_key}\'</a>'
        )
        headerbar = f"<b>Potentiostat Visualizer module for server {server_link}</b>"
        self.layout = layout(
            [
                [Spacer(width=20), Div(text=headerbar, width=1004, height=15)],
                [self.input_max_points],
                [
                    Paragraph(text="""x-axis:""", width=500, height=15),
                    Paragraph(text="""y-axis:""", width=500, height=15),
                ],
                [self.xaxis_selector_group, self.yaxis_selector_group],
                Spacer(height=10),
                *self.plot_divs,
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
        for ch, auuid in self.channel_action_uuid.items():
            self.reset_plot(ch, auuid, forceupdate=True)

    def cleanup_session(self, session_context):
        self.vis.print_message(
            f"'{self.potentiostat_key}' Bokeh session closed", info=True
        )
        self.IOloop_data_run = False
        self.IOtask.cancel()

    def callback_selector_change(self, attr, old, new):
        for ch in self.channel_action_uuid:
            self.reset_plot(ch)

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
        self.vis.print_message(
            f" ... potentiostat visualizer subscribing to: {self.data_url}"
        )
        while True:
            if time.time() - self.last_update_time >= self.update_rate:
                messages = await self.wss.read_messages()
                self.vis.doc.add_next_tick_callback(partial(self.add_points, messages))
                self.last_update_time = time.time()
            await asyncio.sleep(0.01)

    def add_points(self, datapackage_list: list):
        for data_package in datapackage_list:
            if (
                data_package.datamodel.status in VALID_DATA_STATUS
                and data_package.action_name in VALID_ACTION_NAME
            ):
                for _, uuid_dict in data_package.datamodel.data.items():
                    data_dict = {k: [] for k in self.data_dict_keys}
                    channels = uuid_dict.get("channel", [])
                    if channels:
                        pstat_channel = channels[0]
                        # only resets if axis selector or action_uuid changes
                        self.reset_plot(
                            channel=pstat_channel,
                            new_action_uuid=str(data_package.action_uuid),
                        )
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
                        self.channel_datasources[pstat_channel].stream(
                            data_dict, rollover=self.max_points
                        )

    def _add_plots(self, channel):
        # clear legend
        if self.channel_plots[channel].renderers:
            self.channel_plots[channel].legend.items = []
        if self.channel_plots_prev[channel].renderers:
            self.channel_plots_prev[channel].legend.items = []

        # remove all old lines
        self.channel_plots[channel].renderers = []
        self.channel_plots_prev[channel].renderers = []

        self.channel_plots[channel].title.text = (
            f"active action_uuid: {self.channel_action_uuid[channel]}"
        )
        self.channel_plots_prev[channel].title.text = (
            f"last action_uuid: {self.channel_action_uuid_prev[channel]}"
        )
        xstr = self.data_dict_keys[self.xselect]
        ystr = self.data_dict_keys[self.yselect]
        self.vis.print_message(f"{xstr}, {ystr}")
        colors = ["red", "blue", "orange", "green"]
        self.channel_plots[channel].line(
            x=xstr,
            y=ystr,
            line_color=colors[0],
            source=self.channel_datasources[channel],
            name=self.channel_action_uuid[channel],
            legend_label=ystr,
        )
        self.channel_plots_prev[channel].line(
            x=xstr,
            y=ystr,
            line_color=colors[0],
            source=self.channel_datasources_prev[channel],
            name=self.channel_action_uuid_prev[channel],
            legend_label=ystr,
        )

    def reset_plot(self, channel, new_action_uuid=None, forceupdate: bool = False):
        if self.channel_action_uuid[channel] != new_action_uuid or forceupdate:
            if new_action_uuid is not None:
                self.vis.print_message(f" ... reseting channel {channel} graph")
                if self.channel_action_uuid_prev[channel] != "":
                    self.channel_action_uuid_prev[channel] = self.channel_action_uuid[channel]
                    self.channel_datasources_prev[channel] = ColumnDataSource(data=deepcopy(self.channel_datasources[channel].data))
                self.channel_action_uuid[channel] = new_action_uuid
                self.channel_datasources[channel].data = {
                    key: [] for key in self.data_dict_keys
                }
            self._add_plots(channel)
        if (self.xselect != self.xaxis_selector_group.active) or (
            self.yselect != self.yaxis_selector_group.active
        ):
            self.xselect = self.xaxis_selector_group.active
            self.yselect = self.yaxis_selector_group.active
            self._add_plots(channel)
