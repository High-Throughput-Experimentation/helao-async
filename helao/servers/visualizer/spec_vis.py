import websockets
import asyncio
import json
from datetime import datetime
from functools import partial
from copy import deepcopy

from bokeh.models import (
    TextInput,
)
from bokeh.models.widgets import Paragraph
from bokeh.plotting import figure
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


class C_specvis:
    """spectrometer visualizer module class"""

    def __init__(self, visServ: Vis, serv_key: str):
        self.vis = visServ
        self.config_dict = self.vis.server_cfg["params"]
        self.max_spectra = 5

        self.spec_key = serv_key
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

        self.data_dict = {"channel": []}

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

        self._add_plots()

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
            self.data_dict = {"channel": []}

        # update self.data_dict with incoming data package
        for _, data_dict in datapackage.datamodel.data.items():
            # unpack and sort epoch and channels
            epoch = data_dict["epoch_s"]
            dtstr = datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S.%f")
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
