import time
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
from bokeh.models.widgets import DataTable, TableColumn
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource
from bokeh.models.axes import Axis

from helao.servers.vis import Vis


class C_co2:
    """potentiostat visualizer module class"""

    def __init__(self, visServ: Vis, serv_key: str):
        self.vis = visServ
        self.config_dict = self.vis.server_cfg["params"]
        self.update_rate = self.config_dict.get("update_rate", 0.5)
        self.max_points = 500
        self.last_update_time = time.time()

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
        self.table_dict = {}
        self.datasource_table = ColumnDataSource(data=self.table_dict)
        self.update_table_data()

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
        # self.xaxis_selector_group = RadioButtonGroup(
        #     labels=self.data_dict_keys, active=0, width=500
        # )
        # self.yaxis_selector_group = CheckboxButtonGroup(
        #     labels=self.data_dict_keys, active=[1, 3], width=500
        # )

        self.plot = figure(height=300, width=500)
        self.plot.xaxis.axis_label = "Epoch (seconds)"
        self.plot.yaxis.axis_label = "CO2 (ppm)"

        self.table = DataTable(
            source=self.datasource_table,
            columns=[
                TableColumn(field="name", title="name"),
                TableColumn(field="value", title="value"),
            ],
            height=300,
            width=300,
        )
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
                [self.input_max_points, self.input_update_rate],
                # [
                #     Paragraph(text="x-axis selectors", width=500, height=15),
                #     Paragraph(text="y-axis selectors", width=500, height=15),
                # ],
                # [self.xaxis_selector_group, self.yaxis_selector_group],
                Spacer(height=10),
                [self.plot, Spacer(width=20), self.table],
                Spacer(height=10),
            ],
            background="#C0C0C0",
            width=1024,
        )

        # to check if selection changed during ploting
        # self.xselect = self.xaxis_selector_group.active
        # self.yselect = self.yaxis_selector_group.active

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)

    def update_table_data(self):
        self.table_dict["name"] = self.data_dict_keys
        vals = []
        for k in self.data_dict_keys:
            if self.data_dict[k] == []:
                vals.append("")
            else:
                vals.append(self.data_dict[k][0])
        self.table_dict["value"] = vals
        self.datasource_table.data = self.table_dict

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
        self.update_table_data()
        self._add_plots()

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
                            if time.time() - self.last_update_time >= self.update_rate:
                                self.vis.doc.add_next_tick_callback(
                                    partial(self.add_points, datapackage)
                                )
                                self.last_update_time = time.time()
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

        # remove all old lines
        self.plot.renderers = []

        self.plot.line(
            x="epoch_s",
            y="co2_ppm",
            line_color="red",
            source=self.datasource,
        )

    def reset_plot(self, forceupdate: bool = False):
        # self.xselect = self.xaxis_selector_group.active
        # self.yselect = self.yaxis_selector_group.active
        self._add_plots()
