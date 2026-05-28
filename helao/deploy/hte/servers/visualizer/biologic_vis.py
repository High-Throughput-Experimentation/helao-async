import time
import asyncio
from functools import partial
from copy import deepcopy

import pandas as pd
from bokeh.models import (
    RadioButtonGroup,
    TextInput,
)
from bokeh.plotting import figure
from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource
from bokeh.models import Button
from bokeh.events import ButtonClick

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.core.models.hlostatus import HloStatus
from helao.core.servers.vis import Vis
from helao.helpers.ws_utils import WsSubscriber as Wss
from helao.helpers.dispatcher import async_private_dispatcher

VALID_DATA_STATUS = (
    None,
    "active",
    HloStatus.active,
)

AXIS_MAP = {
    "run_CA": ("t_s", "I_A"),
    "run_CP": ("t_s", "Ewe_V"),
    "run_CV": ("Ewe_V", "I_A"),
    "run_OCV": ("t_s", "Ewe_V"),
    "run_PEIS": ("R_ohm", "X_ohm"),
    "run_CAOCV": ("t_s", "I_A"),
}

VALID_ACTION_NAME = [k for k in AXIS_MAP.keys()]


class C_biovis:
    """Bokeh visualizer for a multi-channel Biologic potentiostat server.

    Subscribes to the action server's ``ws_data`` WebSocket and streams
    per-channel time-series plots (active and previous run side-by-side) with
    radio-button x/y selectors, a max-points input, and per-channel stop
    buttons.

    Attributes:
        vis: Host :class:`Vis` instance providing the Bokeh document.
        config_dict: ``params`` block from the visualizer's server config.
        num_channels: Number of Biologic channels to render plots for.
        max_points: Rolling window length per data source.
        update_rate: Minimum seconds between WebSocket polls.
        last_update_time: Epoch timestamp of the most recent poll.
        potentiostat_key: Server key of the action server being visualized.
        potserv_config: Mapping with ``host``/``port`` for the action server.
        potserv_host: Action server hostname.
        potserv_port: Action server port.
        wss: :class:`WsSubscriber` connected to ``ws_data``.
        data_url: Fully formed ``ws://`` URL for the data WebSocket.
        IOloop_data_run: Liveness flag for the data ingestion task.
        IOloop_stat_run: Liveness flag for the status ingestion task.
        data_dict_keys: Keys streamed per channel data source.
        channel_datasources: Live :class:`ColumnDataSource` per channel.
        channel_datasources_prev: Snapshot of the prior run per channel.
        channel_action_uuid: Current action UUID per channel.
        channel_action_uuid_prev: Previous action UUID per channel.
        layout: Composed Bokeh layout mounted on the document.
        input_max_points: Widget setting ``max_points``.
        xaxis_selector_group: Radio buttons selecting the x-axis variable.
        yaxis_selector_group: Radio buttons selecting the y-axis variable.
        channel_plots: Per-channel live ``figure`` objects.
        channel_plots_prev: Per-channel prior-run ``figure`` objects.
        stop_buttons: Per-channel danger buttons that abort the channel.
        xselect: Cached active index of ``xaxis_selector_group``.
        yselect: Cached active index of ``yaxis_selector_group``.
        IOtask: ``asyncio`` task running :meth:`IOloop_data`.
    """

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Wire up data sources, widgets, plot layout, and start the WS ingest task.

        Args:
            vis_serv: Host :class:`Vis` server providing the Bokeh document.
            serv_key: Configuration key of the Biologic action server to
                subscribe to. If the server is not in the config, ``__init__``
                returns early without registering any roots.
        """
        self.vis = vis_serv
        self.config_dict = self.vis.server_cfg.get("params", {})
        self.num_channels = self.config_dict.get("num_channels", 1)
        self.max_points = 5000
        self.update_rate = 1e-3
        self.last_update_time = time.time()

        self.potentiostat_key = serv_key
        self.potserv_config = self.vis.world_cfg["servers"].get(
            self.potentiostat_key, None
        )
        if self.potserv_config is None:
            return
        self.potserv_host = self.potserv_config.get("host", None)
        self.potserv_port = self.potserv_config.get("port", None)
        self.wss = Wss(self.potserv_host, self.potserv_port, "ws_data")

        self.data_url = (
            f"ws://{self.potserv_config['host']}:{self.potserv_config['port']}/ws_data"
        )

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

        self.data_dict_keys = ["t_s", "Ewe_V", "I_A", "P_W", "R_ohm", "X_ohm"]

        # separate data sources for each channel (biologic channel) 
        # this is the important part - we don't redefine the data sources, we just stream into it
        self.channel_datasources = {
            ch: ColumnDataSource(data={key: [] for key in self.data_dict_keys})
            for ch in range(self.num_channels)
        }
        self.channel_datasources_prev = {
            ch: ColumnDataSource(data={key: [] for key in self.data_dict_keys})
            for ch in range(self.num_channels)
        }
        self.channel_action_uuid = {ch: "" for ch in range(self.num_channels)}
        self.channel_action_uuid_prev = {ch: "" for ch in range(self.num_channels)}

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
        self.yaxis_selector_group = RadioButtonGroup(
            labels=self.data_dict_keys, active=3, width=500
        )
        self.xaxis_selector_group.on_change(
            "active", partial(self.callback_selector_change)
        )
        self.yaxis_selector_group.on_change(
            "active", partial(self.callback_selector_change)
        )

        self.channel_plots = [
            figure(title=f"channel {ch}", height=300, width=500)
            for ch in range(self.num_channels)
        ]

        self.channel_plots_prev = [
            figure(title=f"channel {ch}", height=300, width=500)
            for ch in range(self.num_channels)
        ]

        self.stop_buttons = [
            Button(
                label=f"Stop channel {ch}",
                button_type="danger",
                width=70,
            )
            for ch in range(self.num_channels)
        ]

        for i, x in enumerate(self.stop_buttons):
            x.on_event(ButtonClick, partial(self.callback_stop_measure, channel=i))

        # generate 2-column layout for potentiostat channels
        self.vert_groups = [
            [
                item
                for horiz_group in [
                    (plot, Spacer(width=20), plot_prev)
                    for plot, plot_prev in zip(
                        self.channel_plots,
                        self.channel_plots_prev,
                    )
                ]
                for item in horiz_group
            ]
            for i in range(self.num_channels)
        ]
        self.plot_divs = [
            vert_item
            for vert_group in zip(
                self.stop_buttons,
                self.vert_groups,
                [Spacer(height=10)] * len(self.vert_groups),
            )
            for vert_item in vert_group
        ]

        # combine all sublayouts into a single one
        docs_url = f"http://{self.potserv_host}:{self.potserv_port}/docs#/"
        server_link = (
            f'<a href="{docs_url}" target="_blank">\'{self.potentiostat_key}\'</a>'
        )
        headerbar = f"<b>Potentiostat Visualizer module for server {server_link}</b>"
        self.layout = layout(
            [
                [Spacer(width=20), Div(text=headerbar, width=1004, height=15)],
                [self.input_max_points],
                [
                    Div(text="""x-axis:""", width=500, height=15),
                    Div(text="""y-axis:""", width=500, height=15),
                ],
                [self.xaxis_selector_group, self.yaxis_selector_group],
                Spacer(height=10),
                *self.plot_divs,
            ],
            background="#D6DBDF",
            width=1024,
        )

        # to check if selection changed during ploting
        self.xselect = self.xaxis_selector_group.active
        self.yselect = self.yaxis_selector_group.active

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)
        for ch, _ in self.channel_action_uuid.items():
            self.reset_plot(ch, forceupdate=True)

    def cleanup_session(self, session_context):
        """Cancel the data ingest task when the Bokeh session is torn down.

        Args:
            session_context: Bokeh session context (unused).
        """
        LOGGER.info(f"'{self.potentiostat_key}' Bokeh session closed")
        self.IOloop_data_run = False
        self.IOtask.cancel()

    def callback_selector_change(self, attr, old, new):
        """Re-render every channel plot after the user picks new axes.

        Args:
            attr: Bokeh property name that changed.
            old: Previous selector index.
            new: New selector index.
        """
        for ch in self.channel_action_uuid:
            self.reset_plot(ch)

    def callback_input_max_points(self, attr, old, new, sender):
        """Validate the ``max datapoints`` input and update the rolling window.

        Parses ``new`` as an int, falls back to ``old`` (or ``500``) on bad
        input, then clamps the result to ``[2, 10000]`` before storing it as
        ``self.max_points`` and writing the normalized value back to the
        input widget.

        Args:
            attr: Bokeh property name that changed (``"value"``).
            old: Prior text value.
            new: New text value typed by the user.
            sender: The :class:`TextInput` to refresh with the clamped value.
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
        ``self.update_rate``, reads messages from the subscriber, and
        schedules :meth:`add_points` on the document thread.
        """
        LOGGER.info(f" ... potentiostat visualizer subscribing to: {self.data_url}")
        while True:
            if time.time() - self.last_update_time >= self.update_rate:
                messages = await self.wss.read_messages() # where the data is coming from - reads messages in websocket
                self.vis.doc.add_next_tick_callback(partial(self.add_points, messages))
                self.last_update_time = time.time()
            await asyncio.sleep(0.01)

    def add_points(self, datapackage_list: list):
        """Stream a batch of incoming data packages into the per-channel sources.

        Filters out packages whose ``status`` or ``action_name`` is not
        recognized, calls :meth:`reset_plot` when the channel's action UUID
        changes, normalizes ``NaN`` values, and pads short columns before
        streaming into the active channel's :class:`ColumnDataSource`.

        Args:
            datapackage_list: List of action-server data packages received
                from the WebSocket subscriber.
        """
        for data_package in datapackage_list:
            if (
                data_package.datamodel.status in VALID_DATA_STATUS 
                and data_package.action_name in VALID_ACTION_NAME
            ):
                for _, uuid_dict in data_package.datamodel.data.items():
                    data_dict = {k: [] for k in self.data_dict_keys}
                    channels = uuid_dict.get("channel", [])
                    if channels:
                        pstat_channel = channels[0]
                        # only resets if axis selector or action_uuid changes
                        self.reset_plot(
                            channel=pstat_channel,
                            new_data_package=data_package,
                        )
                        for data_label, data_val in uuid_dict.items():
                            if data_label in self.data_dict_keys:
                                if isinstance(data_val, list):
                                    nanfiltered = [
                                        "NaN" if pd.isna(x) else x for x in data_val
                                    ]
                                    data_dict[data_label] += nanfiltered
                                else:
                                    data_dict[data_label].append(
                                        "NaN" if pd.isna(data_val) else data_val
                                    )

                        # check for missing I_A in OCV
                        max_len = max([len(v) for v in data_dict.values()])
                        for k, v in data_dict.items():
                            if len(v) < max_len:
                                pad_len = max_len - len(v)
                                data_dict[k] += ["NaN"] * pad_len

                        self.channel_datasources[pstat_channel].stream(
                            data_dict, rollover=self.max_points
                        )

    def _add_plots(self, channel):
        """Rebuild the active and previous-run figures for a single channel.

        Clears existing renderers and legends, updates the figure titles with
        the channel's current and previous action UUIDs, then plots the
        currently selected x/y variables against the channel's live and
        snapshot data sources.

        Args:
            channel: Zero-based Biologic channel index to redraw.
        """
        # clear legend
        if self.channel_plots[channel].renderers:
            self.channel_plots[channel].legend.items = []
        if self.channel_plots_prev[channel].renderers:
            self.channel_plots_prev[channel].legend.items = []

        # remove all old lines
        self.channel_plots[channel].renderers = []
        self.channel_plots_prev[channel].renderers = []

        self.channel_plots[channel].title.text = (
            f"[ch:{channel:0d}] active action_uuid: {self.channel_action_uuid[channel]}"
        )
        self.channel_plots_prev[channel].title.text = (
            f"[ch:{channel:0d}] last action_uuid: {self.channel_action_uuid_prev[channel]}"
        )
        xstr = self.data_dict_keys[self.xselect]
        ystr = self.data_dict_keys[self.yselect]
        LOGGER.info(f"{xstr}, {ystr}")
        colors = ["red", "blue", "orange", "green"]
        self.channel_plots[channel].line(
            x=xstr,
            y=ystr,
            line_color=colors[0],
            source=self.channel_datasources[channel],
            name=self.channel_action_uuid[channel],
            legend_label=ystr,
        )
        self.channel_plots_prev[channel].line(
            x=xstr,
            y=ystr,
            line_color=colors[0],
            source=self.channel_datasources_prev[channel],
            name=self.channel_action_uuid_prev[channel],
            legend_label=ystr,
        )

    def reset_plot(self, channel, new_data_package=None, forceupdate: bool = False):
        """Promote live data to "previous" and start a new plot when the action changes.

        If ``new_data_package`` belongs to a different action UUID than the
        one currently bound to ``channel`` (or ``forceupdate`` is set),
        snapshots the live data source to the previous source, resets the
        live data, picks axis defaults from :data:`AXIS_MAP` based on the
        new action name, and rebuilds the plot. Also rebuilds the plot if
        the user changed the axis selector between updates.

        Args:
            channel: Channel index to reset.
            new_data_package: Latest data package whose ``action_uuid`` /
                ``action_name`` drive the reset. May be ``None`` to only
                respond to axis-selector changes.
            forceupdate: If ``True``, force a rebuild even when the UUID
                hasn't changed.
        """
        new_action_uuid = ""
        action_name = ""
        if new_data_package is not None:
            new_action_uuid = str(new_data_package.action_uuid)
            action_name = new_data_package.action_name
            if self.channel_action_uuid[channel] != new_action_uuid or forceupdate:
                LOGGER.info(f" ... reseting channel {channel} graph")
                self.channel_action_uuid_prev[channel] = self.channel_action_uuid[
                    channel
                ]
                if self.channel_action_uuid_prev[channel] != "":
                    self.channel_datasources_prev[channel] = ColumnDataSource(
                        data=deepcopy(self.channel_datasources[channel].data)
                    )
                self.channel_action_uuid[channel] = new_action_uuid
                self.channel_datasources[channel].data = {
                    key: [] for key in self.data_dict_keys
                }
                if action_name in AXIS_MAP:
                    xlab, ylab = AXIS_MAP[action_name]
                    self.xaxis_selector_group.update(
                        active=self.data_dict_keys.index(xlab)
                    )
                    self.yaxis_selector_group.update(
                        active=self.data_dict_keys.index(ylab)
                    )
                    self.xselect = self.xaxis_selector_group.active
                    self.yselect = self.yaxis_selector_group.active
                self._add_plots(channel)
        if (self.xselect != self.xaxis_selector_group.active) or (
            self.yselect != self.yaxis_selector_group.active
        ):
            self.xselect = self.xaxis_selector_group.active
            self.yselect = self.yaxis_selector_group.active
            self._add_plots(channel)

    def callback_stop_measure(self, event, channel):
        """Dispatch a private ``stop`` call to the action server for one channel.

        Fired when the user clicks the channel's stop button. Schedules an
        asynchronous private dispatch so the cancel call doesn't block the
        Bokeh document.

        Args:
            event: Bokeh ``ButtonClick`` event (unused).
            channel: Biologic channel index to stop.
        """
        LOGGER.info("stopping gamry measurement")
        self.vis.doc.add_next_tick_callback(
            partial(
                async_private_dispatcher,
                server_key=self.potentiostat_key,
                host=self.potserv_host,
                port=self.potserv_port,
                private_action="stop_private",
                params_dict={"channel": channel},
                json_dict={},
            )
        )
