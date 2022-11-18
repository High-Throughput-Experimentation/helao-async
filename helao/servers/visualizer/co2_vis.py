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

from helao.servers.vis import Vis


class C_co2:
    """potentiostat visualizer module class"""

    def __init__(self, visServ: Vis, serv_key: str):
        self.vis = visServ
        self.config_dict = self.vis.server_cfg["params"]
        self.max_points = 500

        self.live_key = serv_key
        co2serv_config = self.vis.world_cfg["servers"].get(self.live_key, None)
        if co2serv_config is None:
            return
        co2serv_host = co2serv_config.get("host", None)
        co2serv_port = co2serv_config.get("port", None)

        self.data_url = (
            f"ws://{co2serv_config['host']}:{co2serv_config['port']}/ws_live"
        )
        # self.stat_url = f"ws://{co2serv_config["host"]}:{co2serv_config["port"]}/ws_status"

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

        self.data_dict_keys = ["epoch_s", "co2_ppm"]
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
                        text=f'<b>CO2 Sensor module for server <a href="http://{co2serv_host}:{co2serv_port}/docs#/" target="_blank">\'{self.live_key}\'</a></b>',
                        width=1004,
                        height=15,
                    ),
                ],
                [self.input_max_points],
                [
                    Paragraph(text="""epoch (sec):""", width=500, height=15),
                    Paragraph(text="""CO2 (ppm):""", width=500, height=15),
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

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)

    def cleanup_session(self, session_context):
        self.vis.print_message(f"'{self.live_key}' Bokeh session closed", info=True)
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

    def add_points(self, datapackage: dict):
        if len(self.data_dict[self.data_dict_keys[0]]) > self.max_points:
            delpts = len(self.data_dict[self.data_dict_keys[0]]) - self.max_points
            for key in self.data_dict_keys:
                del self.data_dict[key][:delpts]
        latest_epoch = 0
        for datalab, (dataval, epochsec) in datapackage.items():
            if isinstance(dataval, list):
                self.data_dict[datalab] += dataval
            else:
                self.data_dict[datalab].append(dataval)
            latest_epoch = max([epochsec, latest_epoch])
        self.data_dict["epoch_s"].append(latest_epoch)

        self.datasource.data = self.data_dict

    async def IOloop_data(self):  # non-blocking coroutine, updates data source
        self.vis.print_message(
            f" ... CO2 sensor visualizer subscribing to: {self.data_url}"
        )
        retry_limit = 5
        for _ in range(retry_limit):
            try:
                async with websockets.connect(self.data_url) as ws:
                    self.IOloop_data_run = True
                    while self.IOloop_data_run:
                        try:
                            datapackage = json.loads(await ws.recv())
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

        self.plot.line(
            x="epoch_s",
            y="co2_ppm",
            line_color="red",
            source=self.datasource,
            name=self.cur_action_uuid,
        )
        # self.plot_prev.line(
        #     x=xstr,
        #     y="t_s",
        #     line_color=colors[color_count],
        #     source=self.datasource_prev,
        #     name=self.prev_action_uuid,
        #     legend_label="t_s",
        # )

    def reset_plot(self, new_action_uuid: UUID, forceupdate: bool = False):
        self.xselect = self.xaxis_selector_group.active
        self.yselect = self.yaxis_selector_group.active
        self._add_plots()
