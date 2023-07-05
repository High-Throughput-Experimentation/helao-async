import time
import asyncio
from functools import partial
from datetime import datetime

from bokeh.models import (
    TextInput,
)
from bokeh.plotting import figure
from bokeh.models.widgets import Div
from bokeh.models.widgets import DataTable, TableColumn
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource, DatetimeTickFormatter

from helao.servers.vis import Vis
from helao.helpers.ws_subscriber import WsSubscriber as Wss


class C_mfc:
    """mass flow controller visualizer module class"""

    def __init__(self, vis_serv: Vis, serv_key: str):
        self.vis = vis_serv
        self.actsrv_cfg = self.vis.world_cfg["servers"][serv_key]["params"]
        self.config_dict = self.vis.server_cfg["params"]
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
            "pressure",
            "temperature",
            # "total_flow",
            "volumetric_flow",
            "hold_valve",
            # "time_now",
        ]

        self.data_dict_keys = ["datetime"]
        self.devices = sorted(self.actsrv_cfg["devices"].keys())
        for device_name in self.devices:
            for suffix in self.data_suffices:
                self.data_dict_keys.append(f"{device_name}__{suffix}")
        self.datasource = ColumnDataSource(data={k: [] for k in self.data_dict_keys})
        print(self.datasource.data.keys())
        self.datasource_table = ColumnDataSource(
            data={k: [] for k in ["name", "value"]}
        )
        print(self.datasource_table.data.keys())

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
            minsec="%T",
            minutes="%T",
            hourmin="%T",
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
            background="#C0C0C0",
            width=1024,
        )

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)
        self._add_plots()

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

    def add_points(self, datapackage_list: list):
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

            
        self.datasource.stream(data_dict, rollover=self.max_points)
        keys = list(data_dict.keys())
        values = [data_dict[k][-1] for k in keys]
        table_data_dict = {"name": keys, "value": values}
        self.datasource_table.stream(table_data_dict, rollover=len(keys))
        if not self.plot.renderers:
            self._add_plots()

    async def IOloop_data(self):  # non-blocking coroutine, updates data source
        self.vis.print_message(
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
            await asyncio.sleep(0.001)

    def _add_plots(self):
        # clear legend
        if self.plot.renderers:
            self.plot.legend.items = []

        # remove all old lines
        self.plot.renderers = []

        colors = ["red", "blue", "green", "orange"]
        for dev_name, color in zip(self.devices, colors[: len(self.devices)]):
            modelist = self.datasource.data[f"{dev_name}__control_point"]
            if modelist:
                if (
                    modelist[-1].strip()
                    == "mass flow"
                ):
                    self.plot.yaxis.axis_label = "Flow rate (sccm)"
                    yvar = "mass_flow"
                else:
                    self.plot.yaxis.axis_label = "Pressure (psia)"
                    yvar = "pressure"

                self.plot.line(
                    x="datetime",
                    y=f"{dev_name}__{yvar}",
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

    def reset_plot(self, forceupdate: bool = False):
        # self.xselect = self.xaxis_selector_group.active
        # self.yselect = self.yaxis_selector_group.active
        self._add_plots()
