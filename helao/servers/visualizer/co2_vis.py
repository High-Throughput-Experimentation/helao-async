import websockets
import asyncio
import json
from functools import partial
from uuid import UUID
from copy import deepcopy

from bokeh.models import (
    CheckboxButtonGroup,
    RadioButtonGroup,
    TextInput,
)
from bokeh.models.widgets import Paragraph
from bokeh.plotting import figure
from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource

from helaocore.models.data import DataPackageModel
from helao.servers.vis import Vis


class C_potvis:
    """potentiostat visualizer module class"""

    def __init__(self, visServ: Vis, serv_key: str):
        self.vis = visServ
        self.config_dict = self.vis.server_cfg["params"]
        self.max_points = 500

        self.potentiostat_key = serv_key
        potserv_config = self.vis.world_cfg["servers"].get(self.potentiostat_key, None)
        if potserv_config is None:
            return
        potserv_host = potserv_config.get("host", None)
        potserv_port = potserv_config.get("port", None)

        self.data_url = (
            f"ws://{potserv_config['host']}:{potserv_config['port']}/ws_data"
        )
        # self.stat_url = f"ws://{potserv_config["host"]}:{potserv_config["port"]}/ws_status"

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

        self.data_dict_keys = ["t_s", "Ewe_V", "Ach_V", "I_A"]
        self.data_dict = {key: [] for key in self.data_dict_keys}

        self.datasource = ColumnDataSource(data=self.data_dict)
        self.datasource_prev = ColumnDataSource(data=deepcopy(self.data_dict))
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

        self.xaxis_selector_group = RadioButtonGroup(
            labels=self.data_dict_keys, active=0, width=500
        )
        self.yaxis_selector_group = CheckboxButtonGroup(
            labels=self.data_dict_keys, active=[1, 3], width=500
        )

        self.plot = figure(title="Title", height=300, width=500)

        self.plot_prev = figure(title="Title", height=300, width=500)
        # combine all sublayouts into a single one
        self.layout = layout(
            [
                [
                    Spacer(width=20),
                    Div(
                        text=f'<b>Potentiostat Visualizer module for server <a href="http://{potserv_host}:{potserv_port}/docs#/" target="_blank">\'{self.potentiostat_key}\'</a></b>',
                        width=1004,
                        height=15,
                    ),
                ],
                [self.input_max_points],
                [
                    Paragraph(text="""x-axis:""", width=500, height=15),
                    Paragraph(text="""y-axis:""", width=500, height=15),
                ],
                [self.xaxis_selector_group, self.yaxis_selector_group],
                Spacer(height=10),
                [self.plot, Spacer(width=20), self.plot_prev],
                Spacer(height=10),
            ],
            background="#C0C0C0",
            width=1024,
        )

        # to check if selection changed during ploting
        self.xselect = self.xaxis_selector_group.active
        self.yselect = self.yaxis_selector_group.active

        self.reset_plot(self.cur_action_uuid, forceupdate=True)

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)

    def cleanup_session(self, session_context):
        self.vis.print_message(
            f"'{self.potentiostat_key}' Bokeh session closed", info=True
        )
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

    def add_points(self, datapackage: DataPackageModel):
        def _add_helper(datadict, pointlist):
            for pt in pointlist:
                datadict.append(pt)

        self.reset_plot(str(datapackage.action_uuid))
        if len(self.data_dict[self.data_dict_keys[0]]) > self.max_points:
            delpts = len(self.data_dict[self.data_dict_keys[0]]) - self.max_points
            for key in self.data_dict_keys:
                del self.data_dict[key][:delpts]
        for _, data_dict in datapackage.datamodel.data.items():
            datalen = len(list(data_dict.values())[0])
            for key in self.data_dict_keys:
                _add_helper(
                    datadict=self.data_dict[key],
                    pointlist=data_dict.get(key, [0 for i in range(datalen)]),
                )

        self.datasource.data = self.data_dict

    async def IOloop_data(self):  # non-blocking coroutine, updates data source
        self.vis.print_message(
            f" ... potentiostat visualizer subscribing to: {self.data_url}"
        )
        retry_limit = 5
        for _ in range(retry_limit):
            try:
                async with websockets.connect(self.data_url) as ws:
                    self.IOloop_data_run = True
                    while self.IOloop_data_run:
                        try:
                            datapackage = DataPackageModel(
                                **json.loads(await ws.recv())
                            )
                            datastatus = datapackage.datamodel.status
                            if (
                                datapackage.action_name
                                in (
                                    "run_LSV",
                                    "run_CA",
                                    "run_CP",
                                    "run_CV",
                                    "run_EIS",
                                    "run_OCV",
                                )
                                and datastatus in valid_data_status
                            ):
                                self.vis.doc.add_next_tick_callback(
                                    partial(self.add_points, datapackage)
                                )
                        except Exception:
                            self.IOloop_data_run = False
                    await ws.close()
                    self.IOloop_data_run = False
            except Exception:
                self.vis.print_message(
                    f"failed to subscribe to "
                    f"{self.data_url}"
                    "trying again in 1sec",
                    info=True,
                )
                await asyncio.sleep(1)
            if not self.IOloop_data_run:
                self.vis.print_message("IOloop closed", info=True)
                break

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
        xstr = ""
        if self.xaxis_selector_group.active == 0:
            xstr = "t_s"
        elif self.xaxis_selector_group.active == 1:
            xstr = "Ewe_V"
        elif self.xaxis_selector_group.active == 2:
            xstr = "Ach_V"
        else:
            xstr = "I_A"
        colors = ["red", "blue", "yellow", "green"]
        color_count = 0
        for i in self.yaxis_selector_group.active:
            if i == 0:
                self.plot.line(
                    x=xstr,
                    y="t_s",
                    line_color=colors[color_count],
                    source=self.datasource,
                    name=self.cur_action_uuid,
                    legend_label="t_s",
                )
                self.plot_prev.line(
                    x=xstr,
                    y="t_s",
                    line_color=colors[color_count],
                    source=self.datasource_prev,
                    name=self.prev_action_uuid,
                    legend_label="t_s",
                )
            elif i == 1:
                self.plot.line(
                    x=xstr,
                    y="Ewe_V",
                    line_color=colors[color_count],
                    source=self.datasource,
                    name=self.cur_action_uuid,
                    legend_label="Ewe_V",
                )
                self.plot_prev.line(
                    x=xstr,
                    y="Ewe_V",
                    line_color=colors[color_count],
                    source=self.datasource_prev,
                    name=self.prev_action_uuid,
                    legend_label="Ewe_V",
                )
            elif i == 2:
                self.plot.line(
                    x=xstr,
                    y="Ach_V",
                    line_color=colors[color_count],
                    source=self.datasource,
                    name=self.cur_action_uuid,
                    legend_label="Ach_V",
                )
                self.plot_prev.line(
                    x=xstr,
                    y="Ach_V",
                    line_color=colors[color_count],
                    source=self.datasource_prev,
                    name=self.prev_action_uuid,
                    legend_label="Ach_V",
                )
            else:
                self.plot.line(
                    x=xstr,
                    y="I_A",
                    line_color=colors[color_count],
                    source=self.datasource,
                    name=self.cur_action_uuid,
                    legend_label="I_A",
                )
                self.plot_prev.line(
                    x=xstr,
                    y="I_A",
                    line_color=colors[color_count],
                    source=self.datasource_prev,
                    name=self.prev_action_uuid,
                    legend_label="I_A",
                )
            color_count += 1

    def reset_plot(self, new_action_uuid: UUID, forceupdate: bool = False):
        if (new_action_uuid != self.cur_action_uuid) or forceupdate:
            self.vis.print_message(" ... reseting Gamry graph")
            self.prev_action_uuid = self.cur_action_uuid
            self.cur_action_uuid = new_action_uuid

            # copy old data to "prev" plot
            self.datasource_prev.data = {
                deepcopy(key): deepcopy(val)
                for key, val in self.datasource.data.items()
            }
            self.data_dict = {key: [] for key in self.data_dict_keys}
            self.datasource.data = self.data_dict
            self._add_plots()

        elif (self.xselect != self.xaxis_selector_group.active) or (
            self.yselect != self.yaxis_selector_group.active
        ):
            self.xselect = self.xaxis_selector_group.active
            self.yselect = self.yaxis_selector_group.active
            self._add_plots()
