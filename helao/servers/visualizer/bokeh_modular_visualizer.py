__all__ = ["makeBokehApp"]


import websockets
import asyncio
import json
from datetime import datetime
from functools import partial
from socket import gethostname
from uuid import UUID
from copy import deepcopy

from bokeh.models import (
    CheckboxButtonGroup,
    RadioButtonGroup,
    TextInput,
)
from bokeh.models.widgets import Paragraph
from bokeh.plotting import figure
from bokeh.palettes import small_palettes
from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource
from bokeh.models import DataTable, TableColumn


from helaocore.models.data import DataPackageModel
from helaocore.models.hlostatus import HloStatus
from helao.helpers.make_vis_serv import makeVisServ
from helao.servers.vis import Vis
from helao.helpers.config_loader import config_loader
from helao.helpers.dispatcher import async_private_dispatcher
from helaocore.error import ErrorCodes


valid_data_status = (
    None,
    HloStatus.active,
)


def async_partial(f, *args):
    async def f2(*args2):
        result = f(*args, *args2)
        if asyncio.iscoroutinefunction(f):
            result = await result
        return result

    return f2


class C_nidaqmxvis:
    """NImax visualizer module class"""

    def __init__(self, visServ: Vis, nidaqmx_key: str):
        self.vis = visServ
        self.config_dict = self.vis.server_cfg["params"]
        self.max_points = 500
        self.nidaqmx_key = nidaqmx_key
        nidaqmxserv_config = self.vis.world_cfg["servers"].get(self.nidaqmx_key, None)
        if nidaqmxserv_config is None:
            return
        nidaqmxserv_host = nidaqmxserv_config.get("host", None)
        nidaqmxserv_port = nidaqmxserv_config.get("port", None)

        self.data_url = (
            f"ws://{nidaqmxserv_config['host']}:{nidaqmxserv_config['port']}/ws_data"
        )
        # self.stat_url = f"ws://{nidaqmxserv_config["host"]}:{nidaqmxserv_config["port"]}/ws_status"

        self.IOloop_data_run = False

        self.activeCell = [True for _ in range(9)]

        self.data_dict_keys = [
            "t_s",
            "Icell1_A",
            "Icell2_A",
            "Icell3_A",
            "Icell4_A",
            "Icell5_A",
            "Icell6_A",
            "Icell7_A",
            "Icell8_A",
            "Icell9_A",
            "Ecell1_V",
            "Ecell2_V",
            "Ecell3_V",
            "Ecell4_V",
            "Ecell5_V",
            "Ecell6_V",
            "Ecell7_V",
            "Ecell8_V",
            "Ecell9_V",
        ]

        self.data_dict = {key: [] for key in self.data_dict_keys}

        self.sourceIV = ColumnDataSource(data=self.data_dict)
        self.sourceIV_prev = ColumnDataSource(data=deepcopy(self.data_dict))

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

        self.paragraph1 = Paragraph(text="""cells:""", width=50, height=15)
        self.yaxis_selector_group = CheckboxButtonGroup(
            labels=[f"{i+1}" for i in range(9)], active=[i for i in range(9)]
        )
        # to check if selection changed during ploting
        self.yselect = self.yaxis_selector_group.active

        self.plot_VOLT = figure(title="CELL VOLTs", height=300, width=500)
        self.plot_CURRENT = figure(title="CELL CURRENTs", height=300, width=500)

        self.plot_VOLT_prev = figure(title="prev. CELL VOLTs", height=300, width=500)
        self.plot_CURRENT_prev = figure(
            title="prev. CELL CURRENTs", height=300, width=500
        )

        self.reset_plot(self.cur_action_uuid, forceupdate=True)

        # combine all sublayouts into a single one
        self.layout = layout(
            [
                [
                    Spacer(width=20),
                    Div(
                        text=f'<b>NImax Visualizer module for server <a href="http://{nidaqmxserv_host}:{nidaqmxserv_port}/docs#/" target="_blank">\'{self.nidaqmx_key}\'</a></b>',
                        width=1004,
                        height=15,
                    ),
                ],
                [self.input_max_points],
                [self.paragraph1],
                [self.yaxis_selector_group],
                Spacer(height=10),
                [self.plot_VOLT, self.plot_VOLT_prev],
                Spacer(height=10),
                [self.plot_CURRENT, self.plot_CURRENT_prev],
                Spacer(height=10),
            ],
            background="#C0C0C0",
            width=1024,
        )

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)

    def cleanup_session(self, session_context):
        self.vis.print_message(f"'{self.nidaqmx_key}' Bokeh session closed", info=True)
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

        # they are all in sequence of cell1 to cell9 in the dict
        cellnum = 1

        for _, data_dict in datapackage.datamodel.data.items():
            datalen = len(list(data_dict.values())[0])
            for key in data_dict:
                if key == "t_s" and cellnum == 1:
                    _add_helper(
                        datadict=self.data_dict[key],
                        pointlist=data_dict.get(key, [0 for i in range(datalen)]),
                    )
                elif key == "Icell_A":
                    _add_helper(
                        datadict=self.data_dict[f"Icell{cellnum}_A"],
                        pointlist=data_dict.get(key, [0 for i in range(datalen)]),
                    )
                elif key == "Ecell_V":
                    _add_helper(
                        datadict=self.data_dict[f"Ecell{cellnum}_V"],
                        pointlist=data_dict.get(key, [0 for i in range(datalen)]),
                    )

            cellnum += 1

        self.sourceIV.data = self.data_dict

    async def IOloop_data(self):  # non-blocking coroutine, updates data source
        self.vis.print_message(f" ... NI visualizer subscribing to: {self.data_url}")
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
                                datapackage.action_name in ("cellIV")
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
        # remove all old lines and clear legend
        if self.plot_VOLT.renderers:
            self.plot_VOLT.legend.items = []

        if self.plot_CURRENT.renderers:
            self.plot_CURRENT.legend.items = []

        if self.plot_VOLT_prev.renderers:
            self.plot_VOLT_prev.legend.items = []

        if self.plot_CURRENT_prev.renderers:
            self.plot_CURRENT_prev.legend.items = []

        self.plot_VOLT.renderers = []
        self.plot_CURRENT.renderers = []

        self.plot_VOLT_prev.renderers = []
        self.plot_CURRENT_prev.renderers = []

        self.plot_VOLT.title.text = f"action_uuid: {self.cur_action_uuid}"
        self.plot_CURRENT.title.text = f"action_uuid: {self.cur_action_uuid}"
        # self.plot_VOLT_prev.title.text = ("action_uuid: "+self.prev_action_uuid)
        # self.plot_VOLT_prev.title.text = ("action_uuid: "+self.prev_action_uuid)

        colors = small_palettes["Category10"][9]
        for i in self.yaxis_selector_group.active:
            _ = self.plot_VOLT.line(
                x="t_s",
                y=f"Ecell{i+1}_V",
                source=self.sourceIV,
                name=f"Ecell{i+1}_V",
                line_color=colors[i],
                legend_label=f"Ecell{i+1}_V",
            )
            _ = self.plot_CURRENT.line(
                x="t_s",
                y=f"Icell{i+1}_A",
                source=self.sourceIV,
                name=f"Icell{i+1}_A",
                line_color=colors[i],
                legend_label=f"Icell{i+1}_A",
            )
            _ = self.plot_VOLT_prev.line(
                x="t_s",
                y=f"Ecell{i+1}_V",
                source=self.sourceIV_prev,
                name=f"Ecell{i+1}_V",
                line_color=colors[i],
                legend_label=f"Ecell{i+1}_V",
            )
            _ = self.plot_CURRENT_prev.line(
                x="t_s",
                y=f"Icell{i+1}_A",
                source=self.sourceIV_prev,
                name=f"Icell{i+1}_A",
                line_color=colors[i],
                legend_label=f"Icell{i+1}_A",
            )

    def reset_plot(self, new_action_uuid: UUID, forceupdate: bool = False):
        if (new_action_uuid != self.cur_action_uuid) or forceupdate:
            self.vis.print_message(" ... reseting NImax graph")
            self.prev_action_uuid = self.cur_action_uuid
            self.cur_action_uuid = new_action_uuid

            # copy old data to "prev" plot
            self.sourceIV_prev.data = {
                deepcopy(key): deepcopy(val) for key, val in self.sourceIV.data.items()
            }
            self.data_dict = {key: [] for key in self.data_dict_keys}
            self.sourceIV.data = self.data_dict
            self._add_plots()

        elif self.yselect != self.yaxis_selector_group.active:
            self.yselect = self.yaxis_selector_group.active
            self._add_plots()


class C_potvis:
    """potentiostat visualizer module class"""

    def __init__(self, visServ: Vis, potentiostat_key: str):
        self.vis = visServ
        self.config_dict = self.vis.server_cfg["params"]
        self.max_points = 500

        self.potentiostat_key = potentiostat_key
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


class C_palvis:
    """PAL/archive visualizer module class"""

    def __init__(self, visServ: Vis, pal_key: str):
        self.vis = visServ
        self.config_dict = self.vis.server_cfg["params"]
        self.max_width = 1024
        self.max_smps = 10

        self.pal_key = pal_key
        palserv_config = self.vis.world_cfg["servers"].get(self.pal_key, None)
        if palserv_config is None:
            return
        palserv_host = palserv_config.get("host", None)
        palserv_port = palserv_config.get("port", None)

        self.data_url = (
            f"ws://{palserv_config['host']}:{palserv_config['port']}/ws_data"
        )
        # self.stat_url = f"ws://{palserv_config["host"]}:{palserv_config["port"]}/ws_status"

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

        smptypes = ["solid", "liquid", "gas", "assembly"]

        self.data_dict_keys = [
            "global_label",
            "sample_creation_timecode",
            "comment",
            "volume",
            "ph",
            "electrolyte",
        ]
        self.data_dict = {
            smptype: {key: [] for key in self.data_dict_keys} for smptype in smptypes
        }

        self.datasource = {
            smptype: ColumnDataSource(data=self.data_dict[smptype])
            for smptype in smptypes
        }

        self.sample_tables = {
            smptype: DataTable(
                source=self.datasource[smptype],
                columns=[TableColumn(field=k, title=k) for k in self.data_dict_keys],
                width=self.max_width - 20,
                height=200,
                autosize_mode="fit_columns",
            )
            for smptype in smptypes
        }

        # create visual elements
        self.layout = []

        # input field widget
        self.input_max_smps = TextInput(
            value=f"{self.max_smps}",
            title="num latest samples to return",
            disabled=False,
            width=150,
            height=40,
        )
        # execute on input field change
        self.input_max_smps.on_change(
            "value",
            partial(self.callback_input_max_smps, sender=self.input_max_smps),
        )

        # selector for give_only inheritance
        self.inheritance_selector_group = CheckboxButtonGroup(
            labels=["give_only"],
            active=[],
            width=150,
            height=40,
        )
        self.inheritance_selector_group.on_change(
            "active",
            partial(self.callback_inheritance, sender=self.inheritance_selector_group),
        )
        self.inheritance_select = self.inheritance_selector_group.active

        # combine all sublayouts into a single one
        self.layout = layout(
            [
                [
                    Spacer(width=20),
                    Div(
                        text=f'<b>PAL Visualizer module for server <a href="http://{palserv_host}:{palserv_port}/docs#/" target="_blank">\'{self.pal_key}\'</a></b>',
                        width=1004,
                        height=15,
                    ),
                ],
                [
                    self.input_max_smps,
                    Spacer(width=50),
                    [
                        Div(text="filter by inheritance:"),
                        self.inheritance_selector_group,
                    ],
                ],
                [
                    Spacer(width=20),
                    Div(
                        text="<b>Newest liquid samples:</b>", width=200 + 50, height=15
                    ),
                ],
                [self.sample_tables["liquid"]],
                [
                    Spacer(width=20),
                    Div(
                        text="<b>Newest assembly samples:</b>",
                        width=200 + 50,
                        height=15,
                    ),
                ],
                [self.sample_tables["assembly"]],
                [
                    Spacer(width=20),
                    Div(text="<b>Newest gas samples:</b>", width=200 + 50, height=15),
                ],
                [self.sample_tables["gas"]],
                [
                    Spacer(width=20),
                    Div(text="<b>Newest solid samples:</b>", width=200 + 50, height=15),
                ],
                [self.sample_tables["solid"]],
                Spacer(height=10),
            ],
            background="#C0C0C0",
            width=1024,
        )

        self.reset_plot()

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)

    def cleanup_session(self, session_context):
        self.vis.print_message(f"'{self.pal_key}' Bokeh session closed", info=True)
        self.IOloop_data_run = False
        self.IOtask.cancel()

    def callback_input_max_smps(self, attr, old, new, sender):
        """callback for input_max_smps"""

        def to_int(val):
            try:
                return int(val)
            except ValueError:
                return None

        newpts = to_int(new)
        self.max_smps = newpts
        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.max_smps}")
        )
        self.reset_plot()

    def update_input_value(self, sender, value):
        sender.value = value

    def update_inheritance_selector(self):
        self.inheritance_select = self.inheritance_selector_group.active

    def callback_inheritance(self, attr, old, new, sender):
        """callback for inheritance_select"""
        self.vis.doc.add_next_tick_callback(partial(self.update_inheritance_selector))
        self.reset_plot()

    async def add_points(self):
        # pull latest sample lists from PAL server and populate self.datasource.data
        # keep global_label, sample_creation_timecode, comment, volume, ph, electrolyte
        resp, err = await async_private_dispatcher(
            self.vis.world_cfg,
            "PAL",
            "list_new_samples",
            {
                "num_smps": self.max_smps,
                "give_only": "true" if 0 in self.inheritance_select else "false",
            },
            {},
        )
        if err == ErrorCodes.none:
            for smptype in ["solid", "liquid", "gas", "assembly"]:
                for k in self.data_dict_keys:
                    self.data_dict[smptype][k] = [d.get(k, None) for d in resp[smptype]]
                self.data_dict[smptype]["sample_creation_timecode"] = [
                    datetime.fromtimestamp(v / 1e9).strftime("%Y-%m-%d %H:%M:%S")
                    for v in self.data_dict[smptype]["sample_creation_timecode"]
                ]
                self.datasource[smptype].data = self.data_dict[smptype]

    async def IOloop_data(self):  # non-blocking coroutine, updates data source
        self.vis.print_message(f" ... PAL visualizer subscribing to: {self.data_url}")
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
                            if datastatus in valid_data_status:
                                self.vis.doc.add_next_tick_callback(
                                    async_partial(self.add_points)
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

    def reset_plot(self):
        # copy old data to "prev" plot
        self.vis.doc.add_next_tick_callback(partial(self.add_points))


class C_specvis:
    """spectrometer visualizer module class"""

    def __init__(self, visServ: Vis, spec_key: str):
        self.vis = visServ
        self.config_dict = self.vis.server_cfg["params"]
        self.max_spectra = 5

        self.spec_key = spec_key
        specserv_config = self.vis.world_cfg["servers"].get(self.spec_key, None)
        if specserv_config is None:
            return
        specserv_host = specserv_config.get("host", None)
        specserv_port = specserv_config.get("port", None)

        self.data_url = (
            f"ws://{specserv_config['host']}:{specserv_config['port']}/ws_data"
        )

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

        self.data_dict = {}

        self.datasource = ColumnDataSource(data=self.data_dict)
        self.datasource_prev = ColumnDataSource(data=deepcopy(self.data_dict))

        self.cur_action_uuid = ""
        self.prev_action_uuid = ""

        # create visual elements
        self.layout = []

        self.input_max_spectra = TextInput(
            value=f"{self.max_spectra}",
            title="max num spectra",
            disabled=False,
            width=150,
            height=40,
        )
        self.input_max_spectra.on_change(
            "value",
            partial(self.callback_input_max_spectra, sender=self.input_max_spectra),
        )

        # self.xaxis_selector_group = RadioButtonGroup(
        #     labels=self.data_dict_keys, active=0, width=500
        # )
        # self.yaxis_selector_group = CheckboxButtonGroup(
        #     labels=self.data_dict_keys, active=[1, 3], width=500
        # )

        self.plot = figure(title="Title", height=300, width=500)

        self.plot_prev = figure(title="Title", height=300, width=500)
        # combine all sublayouts into a single one
        self.layout = layout(
            [
                [
                    Spacer(width=20),
                    Div(
                        text=f'<b>Spectrometer Visualizer module for server <a href="http://{specserv_host}:{specserv_port}/docs#/" target="_blank">\'{self.spec_key}\'</a></b>',
                        width=1004,
                        height=15,
                    ),
                ],
                [self.input_max_spectra],
                [
                    Paragraph(text="""x-axis:""", width=500, height=15),
                    Paragraph(text="""y-axis:""", width=500, height=15),
                ],
                # [self.xaxis_selector_group, self.yaxis_selector_group],
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

        self.reset_plot(self.cur_action_uuid, forceupdate=True)

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)

    def cleanup_session(self, session_context):
        self.vis.print_message(f"'{self.spec_key}' Bokeh session closed", info=True)
        self.IOloop_data_run = False
        self.IOtask.cancel()

    def callback_input_max_spectra(self, attr, old, new, sender):
        """callback for input_max_spectra"""

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

        self.max_spectra = newpts

        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.max_spectra}")
        )

    def update_input_value(self, sender, value):
        sender.value = value

    async def IOloop_data(self):  # non-blocking coroutine, updates data source
        self.vis.print_message(
            f" ... spectrometer visualizer subscribing to: {self.data_url}"
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
                                    "acquire_spec",
                                    "acquire_spec_adv",
                                    "acquire_spec_extrig",
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

    def add_points(self, datapackage: DataPackageModel):
        # check if uuid has changed
        new_action_uuid = str(datapackage.action_uuid)
        if new_action_uuid != self.cur_action_uuid:
            self.vis.print_message(" ... reseting Spec graph")
            self.prev_action_uuid = self.cur_action_uuid
            self.cur_action_uuid = new_action_uuid

            # copy old data to "prev" plot
            self.datasource_prev.data = {
                deepcopy(key): deepcopy(val)
                for key, val in self.datasource.data.items()
            }
            self.data_dict = {}

        # update self.data_dict with incoming data package
        for _, data_dict in datapackage.datamodel.data.items():
            # unpack and sort epoch and channels
            epoch = data_dict["epoch_ns"]
            dtstr = datetime.fromtimestamp(epoch / 1e9).strftime("%Y-%m-%d %H:%M:%S.%f")
            ch_keys = sorted(
                [k for k in data_dict.keys() if k.startswith("ch_")],
                key=lambda x: int(x.split("_")[-1]),
            )
            ch_vals = [data_dict[k] for k in ch_keys]
            self.data_dict.update({dtstr: ch_vals})

        # trim number of spectra being plotted
        if len(self.data_dict.keys()) > self.max_spectra:
            datetime_keys = sorted(self.data_dict.keys())
            delpts = len(self.data_dict.keys()) - self.max_spectra
            for key in datetime_keys[:delpts]:
                self.data_dict.pop(key)

        # add channel column and update datasource
        self.data_dict.update({"channel": list(range(len(ch_vals)))})
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

        ds_keys = [x for x in sorted(self.datasource.data.keys()) if x != "channel"]
        for i, dt in enumerate(ds_keys):
            self.plot.line(
                x="channel",
                y=dt,
                line_color="blue" if i != len(ds_keys) - 1 else "red",
                source=self.datasource,
                name=self.cur_action_uuid,
                legend_label=dt,
            )

        dsp_keys = [
            x for x in sorted(self.datasource_prev.data.keys()) if x != "channel"
        ]
        for i, dt in enumerate(dsp_keys):
            self.plot_prev.line(
                x="channel",
                y=dt,
                line_color="blue" if i != len(dsp_keys) - 1 else "red",
                source=self.datasource_prev,
                name=self.prev_action_uuid,
                legend_label=dt,
            )


def find_server_names(vis: Vis, fast_key: str) -> list:
    """finds server name for a given fast driver"""
    server_names = []
    for server_name, server_config in vis.world_cfg["servers"].items():
        if server_config.get("fast", "") == fast_key:
            vis.print_message(
                f"found server: '{fast_key}' under '{server_name}'", info=True
            )
            server_names.append(server_name)

    return server_names


def makeBokehApp(doc, confPrefix, servKey, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = makeVisServ(
        config=config,
        server_key=servKey,
        doc=doc,
        server_title=servKey,
        description="Modular Visualizer",
        version=2.0,
        driver_class=None,
    )

    app.vis.doc.add_root(
        layout(
            [
                Spacer(width=20),
                Div(
                    text=f"<b>Visualizer on {gethostname()}</b>",
                    width=1004,
                    height=32,
                    style={"font-size": "200%", "color": "red"},
                ),
            ],
            background="#C0C0C0",
            width=1024,
        )
    )
    app.vis.doc.add_root(Spacer(height=10))

    # create visualizer objects for defined instruments

    # find all configured gamry servers
    potservnames = find_server_names(vis=app.vis, fast_key="gamry_server")
    potvis = []
    for potservname in potservnames:
        potvis.append(C_potvis(visServ=app.vis, potentiostat_key=potservname))

    # find all configured NI servers
    niservnames = find_server_names(vis=app.vis, fast_key="nidaqmx_server")
    NImaxvis = []
    for niservname in niservnames:
        NImaxvis.append(C_nidaqmxvis(visServ=app.vis, nidaqmx_key=niservname))

    # find all configured SPEC servers
    specservnames = find_server_names(vis=app.vis, fast_key="spec_server")
    specvis = []
    for specservname in specservnames:
        specvis.append(C_specvis(visServ=app.vis, spec_key=specservname))

    # find all configured PAL servers
    palservnames = find_server_names(vis=app.vis, fast_key="pal_server")
    palvis = []
    for palservname in palservnames:
        palvis.append(C_palvis(visServ=app.vis, pal_key=palservname))

    return doc
