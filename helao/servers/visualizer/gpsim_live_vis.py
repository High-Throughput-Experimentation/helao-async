import time
import asyncio
from datetime import datetime
from functools import partial

from bokeh.models import (
    TextInput,
)
from bokeh.plotting import figure
from bokeh.models.widgets import Div
from bokeh.models.widgets import DataTable, TableColumn
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource, DatetimeTickFormatter
import numpy as np

from helao.servers.vis import Vis
from helao.helpers.ws_subscriber import WsSubscriber as Wss


class C_gpsimlivevis:
    """GP simulator visualizer module class"""

    def __init__(self, vis_serv: Vis, serv_key: str):
        self.vis = vis_serv
        self.config_dict = self.vis.server_cfg["params"]
        self.update_rate = self.config_dict.get("update_rate", 0.5)
        self.last_update_time = time.time()

        self.live_key = serv_key
        psrv_config = self.vis.world_cfg["servers"].get(self.live_key, None)
        if psrv_config is None:
            return
        host = psrv_config.get("host", None)
        port = psrv_config.get("port", None)
        self.wss = Wss(host, port, "ws_live")

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

        self.data_dict_keys = ["plate_id", "step", "frac_acquired", "last_acquisition"]
        self.hist_keys = ["pred", "gt"]
        self.hists = []

        self.datasource_table = ColumnDataSource(
            data={k: [] for k in self.data_dict_keys}
        )

        # create visual elements
        self.layout = []

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

        self.plot = figure(height=300, width=600, output_backend="webgl")

        self.table = DataTable(
            source=self.datasource_table,
            columns=[
                TableColumn(field="plate_id", title="plate_id", width=20),
                TableColumn(field="step", title="step", width=40),
                TableColumn(field="frac_acquired", title="frac_acq.", width=40),
                TableColumn(field="last_acquisition", title="last_acq.", width=300),
            ],
            height=300,
            width=400,
            index_width=20,
        )
        # combine all sublayouts into a single one
        docs_url = f"http://{host}:{port}/docs#/"
        server_link = f'<a href="{docs_url}" target="_blank">\'{self.live_key}\'</a>'
        headerbar = f"<b>Live vis module for server {server_link}</b>"
        self.layout = layout(
            [
                [Div(text=headerbar, width=1200, height=15)],
                [self.input_update_rate],
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
        data_dict = {}
        hist_dict = {}
        for datapackage in datapackage_list:
            for datalab, (dataval, epochsec) in datapackage.items():
                if datalab in self.data_dict_keys:
                    data_dict[datalab] = (
                        dataval
                        if datalab != "frac_acquired"
                        else [round(x, 4) for x in dataval]
                    )
                elif datalab in self.hist_keys:
                    hist_dict[datalab] = dataval
                latest_epoch = max([epochsec, latest_epoch])

        histquads = []
        if data_dict:
            for i in range(len(data_dict["plate_id"])):
                print(
                    "pred range:", min(hist_dict["pred"][i]), max(hist_dict["pred"][i])
                )
                phist, pedge = np.histogram(
                    hist_dict["pred"][i], bins=100, range=(0.2, 0.7), density=False
                )
                print("gt range:", min(hist_dict["gt"][i]), max(hist_dict["gt"][i]))
                ghist, gedge = np.histogram(
                    hist_dict["gt"][i], bins=100, range=(0.2, 0.7), density=False
                )
                histquads.append((phist, pedge, ghist, gedge))
            self.hists = histquads

        if latest_epoch != 0 and histquads and data_dict:
            self.datasource_table.data = data_dict
            self._add_plots()

    async def IOloop_data(self):  # non-blocking coroutine, updates data source
        self.vis.print_message(" ... Live visualizer receiving messages.")
        while True:
            if time.time() - self.last_update_time >= self.update_rate:
                messages = await self.wss.read_messages()
                self.vis.doc.add_next_tick_callback(partial(self.add_points, messages))
                self.last_update_time = time.time()
            await asyncio.sleep(0.001)

    def _add_plots(self):
        # clear legend
        if self.plot.renderers:
            self.plot.legend.items = []

        # remove all old lines
        self.plot.renderers = []

        colors = ["red", "blue", "green", "orange"]
        for i, htup in enumerate(self.hists):
            self.plot.quad(
                top=htup[0],
                bottom=0,
                left=htup[1][:-1],
                right=htup[1][1:],
                line_color=colors[i],
                fill_color=None,
                alpha=1.0,
                legend_label=f"{self.datasource_table.data['plate_id'][i]} prediction",
            )
            self.plot.quad(
                top=htup[2],
                bottom=0,
                left=htup[3][:-1],
                right=htup[3][1:],
                line_color=None,
                fill_color=colors[i],
                alpha=0.3,
                legend_label=f"{self.datasource_table.data['plate_id'][i]} g.t.",
            )
            self.plot.legend.border_line_alpha = 0.2
            self.plot.legend.background_fill_alpha = 0.2
