import time
import asyncio
from copy import deepcopy
from datetime import datetime
from functools import partial

from bokeh.models import (
    TextInput,
)
from bokeh.plotting import figure
from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource

import matplotlib.cm as cm
import matplotlib.colors as mcolors

from helao.helpers import helao_logging as logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

from helao.core.models.hlostatus import HloStatus

from helao.servers.vis import Vis
from helao.helpers.dispatcher import private_dispatcher
from helao.helpers.ws_subscriber import WsSubscriber as Wss


VALID_DATA_STATUS = (
    None,
    "active",
    HloStatus.active,
)

VALID_ACTION_NAME = (
    "acquire_spec",
    "acquire_spec_adv",
    "acquire_spec_extrig",
    "calibrate_intensity",
)


class C_specvis:
    """spectrometer visualizer module class"""

    def __init__(self, vis_serv: Vis, serv_key: str):
        self.vis = vis_serv
        self.config_dict = self.vis.server_cfg.get("params", {})
        self.max_spectra = 5
        self.downsample = 2
        self.update_rate = 1e-3
        self.last_update_time = time.time()

        self.spec_key = serv_key
        self.specserv_config = self.vis.world_cfg["servers"].get(self.spec_key, None)
        if self.specserv_config is None:
            return
        self.specserv_host = self.specserv_config.get("host", None)
        self.specserv_port = self.specserv_config.get("port", None)
        self.wss = Wss(self.specserv_host, self.specserv_port, "ws_data")

        self.cmap = cm.get_cmap("Reds_r", self.max_spectra)
        self.latest_coloridx = 0

        self.data_url = (
            f"ws://{self.specserv_config['host']}:{self.specserv_config['port']}/ws_data"
        )

        self.wl = private_dispatcher(
            self.spec_key,
            self.specserv_host,
            self.specserv_port,
            "get_wl",
            params_dict={},
            json_dict={},
        )[0]
        LOGGER.info(self.wl)
        self.ev = [1239.8 / x for x in self.wl]
        self.IOloop_data_run = False
        self.IOloop_stat_run = False

        self.data_dict_keys = ["wl", "ev", "trans", "color", "time"]
        self.datasource = ColumnDataSource(
            data={key: [] for key in self.data_dict_keys}
        )
        self.prev_datasource = ColumnDataSource(
            data={key: [] for key in self.data_dict_keys}
        )

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

        self.input_downsample = TextInput(
            value=f"{self.downsample}",
            title="downsampling factor",
            disabled=False,
            width=150,
            height=40,
        )
        self.input_downsample.on_change(
            "value",
            partial(self.callback_input_downsample, sender=self.input_downsample),
        )
        # self.xaxis_selector_group = RadioButtonGroup(
        #     labels=self.data_dict_keys, active=0, width=500
        # )
        # self.yaxis_selector_group = CheckboxButtonGroup(
        #     labels=self.data_dict_keys, active=[1, 3], width=500
        # )

        self.plot = figure(title="Title", height=300, width=500)
        self.plot.xaxis.axis_label = "Wavelength (nm)"
        self.plot.yaxis.axis_label = "Transmittance (counts/sec)"

        self.plot_prev = figure(title="Title", height=300, width=500)
        self.plot_prev.xaxis.axis_label = "Wavelength (nm)"
        self.plot_prev.yaxis.axis_label = "Transmittance (counts/sec)"
        # combine all sublayouts into a single one
        docs_url = f"http://{self.specserv_host}:{self.specserv_port}/docs#/"
        server_link = f'<a href="{docs_url}" target="_blank">\'{self.spec_key}\'</a>'
        headerbar = f"<b>Spectrometer Visualizer module for server {server_link}</b>"
        self.layout = layout(
            [
                [Spacer(width=20), Div(text=headerbar, width=1004, height=15)],
                [self.input_max_spectra, Spacer(width=20), self.input_downsample],
                Spacer(height=10),
                [self.plot, Spacer(width=20), self.plot_prev],
                Spacer(height=10),
            ],
            background="#D6DBDF",
            width=1024,
        )

        # to check if selection changed during ploting
        # self.xselect = self.xaxis_selector_group.active
        # self.yselect = self.yaxis_selector_group.active
        # self._add_plots()

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)
        self.reset_plot(self.cur_action_uuid, forceupdate=True)

    def cleanup_session(self, session_context):
        LOGGER.info(f"'{self.spec_key}' Bokeh session closed")
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
        self.cmap = cm.get_cmap("Reds_r", self.max_spectra)

        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.max_spectra}")
        )

    def callback_input_downsample(self, attr, old, new, sender):
        """callback for input_downsample"""

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
                newpts = 2
        self.downsample = newpts

        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.downsample}")
        )

    def update_input_value(self, sender, value):
        sender.value = value

    async def IOloop_data(self):  # non-blocking coroutine, updates data source
        LOGGER.info(f" ... spectrometer visualizer subscribing to: {self.data_url}")
        while True:
            if time.time() - self.last_update_time >= self.update_rate:
                messages = await self.wss.read_messages()
                self.vis.doc.add_next_tick_callback(partial(self.add_points, messages))
                self.last_update_time = time.time()
            await asyncio.sleep(0.01)

    def add_points(self, datapackage_list: list):
        for data_package in datapackage_list:
            # only resets if axis selector or action_uuid changes
            self.reset_plot(str(data_package.action_uuid))
            if (
                data_package.datamodel.status in VALID_DATA_STATUS
                and data_package.action_name in VALID_ACTION_NAME
            ):
                for _, uuid_dict in data_package.datamodel.data.items():
                    # unpack and sort epoch and channels
                    epoch = uuid_dict["epoch_s"]
                    dtstr = datetime.fromtimestamp(epoch).strftime(
                        "%Y-%m-%d %H:%M:%S.%f"
                    )
                    ch_keys = sorted(
                        [k for k in uuid_dict.keys() if k.startswith("ch_")],
                        key=lambda x: int(x.split("_")[-1]),
                    )
                    data_dict = {
                        "wl": [self.wl[:: self.downsample]],
                        "ev": [self.ev[:: self.downsample]],
                        "trans": [[uuid_dict[k] for k in ch_keys][:: self.downsample]],
                        "color": [mcolors.rgb2hex(self.cmap(0))],
                        "time": [dtstr],
                    }

                    current_colors = self.datasource.data["color"]
                    new_colors = [
                        mcolors.rgb2hex(self.cmap((i + 1) % self.max_spectra))
                        for i, _ in enumerate(current_colors)
                    ]
                    self.datasource.patch(
                        {"color": [(slice(len(new_colors)), new_colors)]}
                    )
                    self.datasource.stream(data_dict, rollover=self.max_spectra)

    def _add_plots(self):
        # # clear legend
        # if self.plot.renderers:
        #     self.plot.legend.items = []

        # if self.plot_prev.renderers:
        #     self.plot_prev.legend.items = []

        # remove all old lines
        self.plot.renderers = []
        self.plot_prev.renderers = []

        self.plot.title.text = f"active action_uuid: {self.cur_action_uuid}"
        self.plot_prev.title.text = f"previous action_uuid: {self.prev_action_uuid}"

        self.plot.multi_line(
            xs="wl",
            ys="trans",
            color="color",
            source=self.datasource,
            name=self.cur_action_uuid,
        )

        self.plot_prev.multi_line(
            xs="wl",
            ys="trans",
            color="color",
            source=self.prev_datasource,
            name=self.prev_action_uuid,
        )

    def reset_plot(self, new_action_uuid=None, forceupdate: bool = False):
        """Clear current plot and move data to previous plot"""
        if self.cur_action_uuid != new_action_uuid or forceupdate:
            if new_action_uuid is not None:
                LOGGER.info(" ... reseting spectrometer graph")
                self.prev_action_uuid = self.cur_action_uuid
                self.prev_datasource.data = dict(deepcopy(self.datasource.data).items())
                self.cur_action_uuid = new_action_uuid
                self.datasource.data = {key: [] for key in self.data_dict_keys}
            self._add_plots()
