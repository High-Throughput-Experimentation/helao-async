import websockets
import asyncio
import json
from datetime import datetime
from functools import partial

from bokeh.models import (
    CheckboxButtonGroup,
    TextInput,
)
from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource
from bokeh.models import DataTable, TableColumn

from helao.helpers import helao_logging as logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

from helao.core.models.hlostatus import HloStatus
from helao.core.models.data import DataPackageModel
from helao.servers.vis import Vis
from helao.helpers.dispatcher import async_private_dispatcher
from helao.core.error import ErrorCodes


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


class C_palvis:
    """PAL/archive visualizer module class"""

    def __init__(self, vis_serv: Vis, serv_key: str):
        self.vis = vis_serv
        self.config_dict = self.vis.server_cfg.get("params", {})
        self.max_width = 1024
        self.max_smps = 10

        self.pal_key = serv_key
        self.palserv_config = self.vis.world_cfg["servers"].get(self.pal_key, None)
        if self.palserv_config is None:
            return
        self.palserv_host = self.palserv_config.get("host", None)
        self.palserv_port = self.palserv_config.get("port", None)

        self.data_url = (
            f"ws://{self.palserv_config['host']}:{self.palserv_config['port']}/ws_data"
        )
        # self.stat_url = f"ws://{self.palserv_config["host"]}:{self.palserv_config["port"]}/ws_status"

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

        smptypes = ["solid", "liquid", "gas", "assembly"]

        self.data_dict_keys = [
            "global_label",
            "sample_creation_timecode",
            "comment",
            "volume_ml",
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
                        text=f'<b>PAL Visualizer module for server <a href="http://{self.palserv_host}:{self.palserv_port}/docs#/" target="_blank">\'{self.pal_key}\'</a></b>',
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
            background="#D6DBDF",
            width=1024,
        )

        self.reset_plot()

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)

    def cleanup_session(self, session_context):
        LOGGER.info(f"'{self.pal_key}' Bokeh session closed")
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
            self.pal_key,
            self.palserv_host,
            self.palserv_port,
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
        LOGGER.info(f" ... PAL visualizer subscribing to: {self.data_url}")
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
                LOGGER.error(
                    f"failed to subscribe to {self.data_url} trying again in 1sec",
                    exc_info=True,
                )
                await asyncio.sleep(1)
            if not self.IOloop_data_run:
                LOGGER.info("IOloop closed")
                break

    def reset_plot(self):
        # copy old data to "prev" plot
        self.vis.doc.add_next_tick_callback(partial(self.add_points))
