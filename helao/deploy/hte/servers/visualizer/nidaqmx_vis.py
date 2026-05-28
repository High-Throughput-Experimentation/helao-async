import time
import asyncio
from functools import partial
from copy import deepcopy

from bokeh.models import (
    CheckboxButtonGroup,
    TextInput,
)
from bokeh.plotting import figure
from bokeh.palettes import Category10
from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.core.models.hlostatus import HloStatus
from helao.core.servers.vis import Vis
from helao.helpers.ws_utils import WsSubscriber as Wss

VALID_DATA_STATUS = (
    None,
    "active",
    HloStatus.active,
)

VALID_ACTION_NAME = ("cellIV",)


class C_nidaqmxvis:
    """Bokeh visualizer for a NI-DAQmx ``cellIV`` action server.

    Subscribes to the server's ``ws_data`` WebSocket and renders nine
    selectable cell voltages and currents (``E``/``I`` per cell) across the
    active and previous actions, each on a dedicated figure.

    Attributes:
        vis: Host :class:`Vis` instance providing the Bokeh document.
        config_dict: ``params`` block from the visualizer's server config.
        max_points: Rolling window length for the data sources.
        update_rate: Minimum seconds between WebSocket polls.
        last_update_time: Epoch timestamp of the most recent poll.
        nidaqmx_key: Server key of the NI-DAQmx action server.
        wss: :class:`WsSubscriber` connected to ``ws_data``.
        data_url: Fully formed ``ws://`` URL for the data WebSocket.
        IOloop_data_run: Liveness flag for the data ingestion task.
        activeCell: Per-cell visibility flags (length 9).
        data_dict_keys: ``t_s`` plus 9 ``Icell{n}_A`` and 9 ``Ecell{n}_V`` keys.
        datasource: Live :class:`ColumnDataSource`.
        prev_datasource: Snapshotted :class:`ColumnDataSource` for the prior action.
        cur_action_uuid: Action UUID currently being plotted.
        prev_action_uuid: Action UUID of the prior run.
        layout: Composed Bokeh layout mounted on the document.
        input_max_points: Widget setting ``max_points``.
        paragraph1: Static ``cells:`` label rendered above the cell selector.
        yaxis_selector_group: Checkbox buttons selecting active cells.
        yselect: Cached active list of ``yaxis_selector_group``.
        plot_VOLT: Active voltage figure.
        plot_CURRENT: Active current figure.
        plot_VOLT_prev: Previous voltage figure.
        plot_CURRENT_prev: Previous current figure.
        IOtask: ``asyncio`` task running :meth:`IOloop_data`.
    """

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Wire up data sources, widgets, plot layout, and start the WS ingest task.

        Args:
            vis_serv: Host :class:`Vis` server providing the Bokeh document.
            serv_key: Configuration key of the NI-DAQmx action server. If the
                server is not in the config, ``__init__`` returns early
                without registering any roots.
        """
        self.vis = vis_serv
        self.config_dict = self.vis.server_cfg.get("params", {})
        self.max_points = 500
        self.update_rate = 1e-3
        self.last_update_time = time.time()
        self.nidaqmx_key = serv_key
        nidaqmxserv_config = self.vis.world_cfg["servers"].get(self.nidaqmx_key, None)
        if nidaqmxserv_config is None:
            return
        nidaqmxserv_host = nidaqmxserv_config.get("host", None)
        nidaqmxserv_port = nidaqmxserv_config.get("port", None)
        self.wss = Wss(nidaqmxserv_port, nidaqmxserv_host, "ws_data")

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

        self.paragraph1 = Div(text="""cells:""", width=50, height=15)
        self.yaxis_selector_group = CheckboxButtonGroup(
            labels=[f"{i+1}" for i in range(9)], active=list(range(9))
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
        docs_url = f"http://{nidaqmxserv_host}:{nidaqmxserv_port}/docs#/"
        server_link = f'<a href="{docs_url}" target="_blank">\'{self.nidaqmx_key}\'</a>'
        headerbar = f"<b>NImax Visualizer module for server {server_link}</b>"
        self.layout = layout(
            [
                [Spacer(width=20), Div(text=headerbar, width=1004, height=15)],
                [self.input_max_points],
                [self.paragraph1],
                [self.yaxis_selector_group],
                Spacer(height=10),
                [self.plot_VOLT, self.plot_VOLT_prev],
                Spacer(height=10),
                [self.plot_CURRENT, self.plot_CURRENT_prev],
                Spacer(height=10),
            ],
            background="#D6DBDF",
            width=1024,
        )

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)

    def cleanup_session(self, session_context):
        """Cancel the data ingest task when the Bokeh session is torn down.

        Args:
            session_context: Bokeh session context (unused).
        """
        LOGGER.info(f"'{self.nidaqmx_key}' Bokeh session closed")
        self.IOloop_data_run = False
        self.IOtask.cancel()

    def callback_input_max_points(self, attr, old, new, sender):
        """Validate the ``max datapoints`` input and update the rolling window.

        Parses ``new`` as an int, falls back to ``old`` (or ``500``) on bad
        input, then clamps to ``[2, 10000]`` before storing it as
        ``self.max_points`` and refreshing the widget.

        Args:
            attr: Bokeh property name that changed.
            old: Prior text value.
            new: New text value typed by the user.
            sender: The :class:`TextInput` to refresh.
        """

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
        """Write ``value`` back onto a Bokeh input widget on the document thread.

        Args:
            sender: Bokeh input widget whose ``value`` is being updated.
            value: New string value to assign.
        """
        sender.value = value

    async def IOloop_data(self):
        """Continuously pull WebSocket data packages and schedule plot updates.

        Runs for the lifetime of the Bokeh session. Each iteration honors
        ``self.update_rate`` and forwards messages to :meth:`add_points` on
        the document thread.
        """
        LOGGER.info(f" ... NImax visualizer subscribing to: {self.data_url}")
        while True:
            if time.time() - self.last_update_time >= self.update_rate:
                messages = await self.wss.read_messages()
                self.vis.doc.add_next_tick_callback(partial(self.add_points, messages))
                self.last_update_time = time.time()
            await asyncio.sleep(0.01)

    def add_points(self, datapackage_list: list):
        """Stream a batch of action-server data packages into the active source.

        Triggers :meth:`reset_plot` on every package so changes in the action
        UUID promote the live data to ``prev_datasource``. Only packages with
        accepted ``status`` and ``action_name`` contribute new samples.

        Args:
            datapackage_list: List of data packages from the subscriber.
        """
        for data_package in datapackage_list:
            data_dict = {k: [] for k in self.data_dict_keys}
            # only resets if axis selector or action_uuid changes
            self.reset_plot(str(data_package.action_uuid))
            if (
                data_package.datamodel.status in VALID_DATA_STATUS
                and data_package.action_name in VALID_ACTION_NAME
            ):
                for _, uuid_dict in data_package.datamodel.data.items():
                    for data_label, data_val in uuid_dict.items():
                        if data_label in self.data_dict_keys:
                            if isinstance(data_val, list):
                                data_dict[data_label] += data_val
                            else:
                                data_dict[data_label].append(data_val)
            self.datasource.stream(data_dict, rollover=self.max_points)

    def _add_plots(self):
        """Rebuild the four cell voltage/current figures.

        Clears existing renderers and legends, retitles each figure with the
        appropriate action UUID, then draws one voltage and one current line
        per selected cell using the ``Category10`` palette.
        """
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
        self.plot_VOLT_prev.title.text = f"action_uuid: {self.prev_action_uuid}"
        self.plot_CURRENT_prev.title.text = f"action_uuid: {self.prev_action_uuid}"

        colors = Category10[10]
        for i in self.yselect:
            _ = self.plot_VOLT.line(
                x="t_s",
                y=f"Ecell{i+1}_V",
                source=self.datasource,
                name=f"Ecell{i+1}_V",
                line_color=colors[i],
                legend_label=f"Ecell{i+1}_V",
            )
            _ = self.plot_CURRENT.line(
                x="t_s",
                y=f"Icell{i+1}_A",
                source=self.datasource,
                name=f"Icell{i+1}_A",
                line_color=colors[i],
                legend_label=f"Icell{i+1}_A",
            )
            _ = self.plot_VOLT_prev.line(
                x="t_s",
                y=f"Ecell{i+1}_V",
                source=self.prev_datasource,
                name=f"Ecell{i+1}_V",
                line_color=colors[i],
                legend_label=f"Ecell{i+1}_V",
            )
            _ = self.plot_CURRENT_prev.line(
                x="t_s",
                y=f"Icell{i+1}_A",
                source=self.prev_datasource,
                name=f"Icell{i+1}_A",
                line_color=colors[i],
                legend_label=f"Icell{i+1}_A",
            )

    def reset_plot(self, new_action_uuid=None, forceupdate: bool = False):
        """Snapshot the live data to ``prev_datasource`` when the action changes.

        On UUID change (or ``forceupdate``) the live data is deep-copied to
        the previous source, ``cur_action_uuid`` is updated, the live data
        is cleared, and the figures are rebuilt. Selector changes also
        trigger a rebuild.

        Args:
            new_action_uuid: Action UUID of the incoming data package.
            forceupdate: If ``True``, force a rebuild even when the UUID
                hasn't changed.
        """
        if self.cur_action_uuid != new_action_uuid or forceupdate:
            if new_action_uuid is not None:
                LOGGER.info(" ... reseting NImax graph")
                self.prev_action_uuid = self.cur_action_uuid
                self.prev_datasource.data = dict(deepcopy(self.datasource.data).items())
                self.cur_action_uuid = new_action_uuid
                self.datasource.data = {key: [] for key in self.data_dict_keys}
            self._add_plots()
        if self.yselect != self.yaxis_selector_group.active:
            self.yselect = self.yaxis_selector_group.active
            self._add_plots()
