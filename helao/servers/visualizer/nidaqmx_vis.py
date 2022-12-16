import websockets
import asyncio
import json
from functools import partial
from uuid import UUID
from copy import deepcopy

from bokeh.models import (
    CheckboxButtonGroup,
    TextInput,
)
from bokeh.models.widgets import Paragraph
from bokeh.plotting import figure
from bokeh.palettes import small_palettes
from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource

from helaocore.models.hlostatus import HloStatus
from helaocore.models.data import DataPackageModel
from helao.servers.vis import Vis


valid_data_status = (
    None,
    HloStatus.active,
)


class C_nidaqmxvis:
    """NImax visualizer module class"""

    def __init__(self, visServ: Vis, serv_key: str):
        self.vis = visServ
        self.config_dict = self.vis.server_cfg["params"]
        self.max_points = 500
        self.nidaqmx_key = serv_key
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
