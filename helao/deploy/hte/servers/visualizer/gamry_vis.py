from copy import deepcopy
from functools import partial

from bokeh.events import ButtonClick
from bokeh.layouts import Spacer, layout
from bokeh.models import (
    Button,
    ColumnDataSource,
    Select,
    TextInput,
)
from bokeh.models.widgets import Div
from bokeh.plotting import figure

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.core.models.hlostatus import HloStatus
from helao.ui.bokeh.theme import (
    SECTION_MARGIN,
    semantic_button_stylesheet,
    stretch_section,
)
from helao.ui.shared.palette import PANEL_BG, SERIES, panel_styles
from helao.core.servers.vis import Vis
from helao.core.servers.vis_subscriber import ActionVisualizer
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
    "run_RCA": ("t_s", "I_A"),
    "run_LSV": ("Ewe_V", "I_A"),
    "run_PEIS": ("Zreal", "Zimag"),
    "run_GEIS": ("Zreal", "Zimag"),
    # "run_EIS": ("Re_Z", "Im_Z"),
}

VALID_ACTION_NAME = [k for k in AXIS_MAP.keys()]


class C_vis(ActionVisualizer):
    """Bokeh visualizer for a Gamry potentiostat action server.

    Subscribes to the server's ``ws_data`` WebSocket and renders the active
    run alongside up to ``max_prev`` recent runs in a side-by-side layout.
    Provides x/y axis dropdowns, max-points and max-previous inputs, and a
    single stop button that aborts the current measurement.
    Common subscriber bring-up, the ``max datapoints`` callback, and the
    ingest loop are inherited from :class:`ActionVisualizer`.

    Attributes:
        max_prev: Maximum number of previous action UUIDs to retain.
        data_dict_keys: Column names streamed into the live data source.
        datasource: :class:`ColumnDataSource` backing the active plot.
        cur_action_uuid: Action UUID currently being plotted.
        prev_datasources: Snapshotted sources keyed by previous action UUID.
        prev_action_uuid: Most recent finished action UUID.
        prev_action_uuids: Ordered list of retained previous UUIDs.
        layout: Composed Bokeh layout mounted on the document.
        input_max_points: Widget setting ``max_points``.
        input_max_prev: Widget setting ``max_prev``.
        button_stop_measure: Bokeh button that requests action cancellation.
        xaxis_selector_group: Dropdown selecting the x-axis variable.
        yaxis_selector_group: Dropdown selecting the y-axis variable.
        plot: ``figure`` for the active action.
        plot_prev: ``figure`` overlaying the previous N actions.
        xselect: Cached selection of ``xaxis_selector_group``, which is
            the data-key name itself rather than an index into
            ``data_dict_keys``.
        yselect: Cached selection of ``yaxis_selector_group``, likewise a
            data-key name.
    """

    SUBSCRIBE_LABEL = "potentiostat visualizer"

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Wire up data sources, widgets, plot layout, and start the WS ingest task.

        Args:
            vis_serv: Host :class:`Vis` server providing the Bokeh document.
            serv_key: Configuration key of the Gamry action server to
                subscribe to. If the server is not in the config,
                ``__init__`` returns early without registering any roots.
        """
        super().__init__(vis_serv, serv_key, max_points=5000)
        if not self.connected:
            return
        self.max_prev = 4

        self.data_dict_keys = ["t_s", "Ewe_V", "I_A", "Zreal", "Zimag", "Zfreq", "Zphz"]
        self.datasource = ColumnDataSource(
            data={key: [] for key in self.data_dict_keys}
        )
        self.cur_action_uuid = ""

        # prev_datasources aren't streamed, replot when axis or action_uuid changes
        self.prev_datasources = {}
        self.prev_action_uuid = ""
        self.prev_action_uuids = []

        # create visual elements
        self.layout = []

        self.input_max_points = TextInput(
            value=f"{self.max_points}",
            title="max datapoints",
            disabled=False,
            width=150,
        )
        self.input_max_points.on_change(
            "value",
            partial(self.callback_input_max_points, sender=self.input_max_points),
        )

        self.input_max_prev = TextInput(
            value=f"{self.max_prev}",
            title="max previous plots",
            disabled=False,
            width=150,
        )
        self.input_max_prev.on_change(
            "value",
            partial(self.callback_input_max_prev, sender=self.input_max_prev),
        )

        self.button_stop_measure = Button(
            label="Stopped",
            button_type="primary",
            width=70,
            # Bottom-aligned so the button lines up with the input boxes beside
            # it rather than with their titles. A Button has no title, so the
            # default start-alignment rides it up to the label row -- measured
            # 20px high of the inputs before this. The titled inputs above also
            # drop their height=40: that forced 9px of slack below a 31px input
            # box, which left the button 8px short even when bottom-aligned.
            align="end",
            stylesheets=[semantic_button_stylesheet()],
        )
        self.button_stop_measure.on_event(ButtonClick, self.callback_stop_measure)

        # Dropdowns rather than radio groups: a row of one button per data key
        # was as wide as the plot beneath it, and the panel now stretches, so
        # the buttons would have stretched with it. A Select carries its own
        # title, so the separate "x-axis:"/"y-axis:" Divs above it are gone.
        self.xaxis_selector_group = Select(
            title="x-axis:",
            value=self.data_dict_keys[0],
            options=self.data_dict_keys,
            width=150,
        )
        self.yaxis_selector_group = Select(
            title="y-axis:",
            value=self.data_dict_keys[3],
            options=self.data_dict_keys,
            width=150,
        )
        self.xaxis_selector_group.on_change(
            "value", partial(self.callback_selector_change)
        )
        self.yaxis_selector_group.on_change(
            "value", partial(self.callback_selector_change)
        )

        self.plot = figure(title="Title", height=300, sizing_mode="stretch_width")
        self.plot_prev = figure(title="Title", height=300, sizing_mode="stretch_width")

        # combine all sublayouts into a single one
        docs_url = f"http://{self.host}:{self.port}/docs#/"
        server_link = f'<a href="{docs_url}" target="_blank">\'{self.serv_key}\'</a>'
        headerbar = f"<b>Potentiostat Visualizer module for server {server_link}</b>"
        self.layout = layout(
            [
                [
                    Spacer(width=20),
                    Div(text=headerbar, sizing_mode="stretch_width", height=15),
                ],
                [
                    self.input_max_points,
                    Spacer(width=20),
                    self.input_max_prev,
                    Spacer(width=20),
                    self.button_stop_measure,
                ],
                [
                    self.xaxis_selector_group,
                    Spacer(width=20),
                    self.yaxis_selector_group,
                ],
                Spacer(height=10),
                [self.plot, Spacer(width=20), self.plot_prev],
                Spacer(height=10),
            ],
            styles=panel_styles(PANEL_BG),
            margin=SECTION_MARGIN,
        )
        stretch_section(self.layout)

        # to check if selection changed during ploting
        self.xselect = self.xaxis_selector_group.value
        self.yselect = self.yaxis_selector_group.value

        self._mount()
        self.reset_plot(forceupdate=True)

    def callback_stop_measure(self, event):
        """Dispatch a private ``stop`` call to the Gamry action server.

        Fired when the user clicks the stop button. Schedules an asynchronous
        private dispatch and resets the button label/style to ``Stopped``.

        Args:
            event: Bokeh ``ButtonClick`` event (unused).
        """
        LOGGER.info("stopping gamry measurement")
        self.vis.doc.add_next_tick_callback(
            partial(
                async_private_dispatcher,
                server_key=self.serv_key,
                host=self.host,
                port=self.port,
                private_action="stop_private",
                params_dict={},
                json_dict={},
            )
        )
        self.button_stop_measure.label = "Stopped"
        self.button_stop_measure.button_type = "primary"

    def callback_selector_change(self, attr, old, new):
        """Re-render plots after the user picks new x/y axes.

        Args:
            attr: Bokeh property name that changed.
            old: Previously selected data key.
            new: Newly selected data key.
        """
        self.reset_plot()

    def callback_input_max_prev(self, attr, old, new, sender):
        """Validate the ``max previous plots`` input.

        Parses ``new`` as an int (defaulting to ``old`` or ``4``), assigns it
        to ``self.max_prev``, and writes the value back to the widget.

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
                newpts = 4

        self.max_prev = newpts

        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.max_prev}")
        )

    def add_points(self, datapackage_list: list):
        """Stream the latest data packages into the active plot's data source.

        Skips packages with unknown ``status`` or ``action_name``, flips the
        sign of ``Zimag`` so impedance plots render with ``-Zimag`` on the
        positive axis, pads short columns with ``"NaN"``, and triggers
        :meth:`reset_plot` when the action UUID changes.

        Args:
            datapackage_list: List of action-server data packages from the
                WebSocket subscriber.
        """
        for data_package in datapackage_list:
            data_dict = {k: [] for k in self.data_dict_keys}
            if (
                data_package.datamodel.status in VALID_DATA_STATUS
                and data_package.action_name in VALID_ACTION_NAME
            ):
                # only resets if axis selector or action_uuid changes
                self.reset_plot(data_package)
                for _, uuid_dict in data_package.datamodel.data.items():
                    for data_label, data_val in uuid_dict.items():
                        if data_label in self.data_dict_keys:
                            if isinstance(data_val, list):
                                if data_label == "Zimag":
                                    data_val = [-1 * val for val in data_val]
                                data_dict[data_label] += data_val
                            else:
                                if data_label == "Zimag":
                                    data_val = -1 * data_val
                                data_dict[data_label].append(data_val)

            # check for missing I_A in OCV
            max_len = max([len(v) for v in data_dict.values()])
            for k, v in data_dict.items():
                if len(v) < max_len:
                    pad_len = max_len - len(v)
                    data_dict[k] += ["NaN"] * pad_len
            self.datasource.stream(data_dict, rollover=self.max_points)

    def _add_plots(self):
        """Rebuild the active and "previous N" figures with the selected axes.

        Clears existing renderers and legends, updates titles with the active
        action UUID and the number of retained previous runs, then plots the
        live data source plus one line per previous data source.
        """
        # clear legend
        if self.plot.renderers:
            self.plot.legend.items = []

        if self.plot_prev.renderers:
            self.plot_prev.legend.items = []

        # remove all old lines
        self.plot.renderers = []
        self.plot_prev.renderers = []

        self.plot.title.text = f"active action_uuid: {self.cur_action_uuid}"
        self.plot_prev.title.text = f"last {len(self.prev_action_uuids)} actions"
        xstr = self.xselect
        ystr = self.yselect
        LOGGER.info(f"{xstr}, {ystr}")
        colors = [SERIES[0], SERIES[1], SERIES[3], SERIES[2]]
        self.plot.line(
            x=xstr,
            y=ystr,
            line_color=colors[0],
            source=self.datasource,
            name=self.cur_action_uuid,
            legend_label=ystr if ystr != "Zimag" else "-Zimag",
        )
        for i, puuid in enumerate(self.prev_action_uuids):
            self.plot_prev.line(
                x=xstr,
                y=ystr,
                line_color=colors[i % len(colors)],
                source=self.prev_datasources[puuid],
                name=puuid,
                # legend_label=puuid.split("-")[0],
                legend_label=f"{i+1}",
            )

    def reset_plot(self, new_data_package=None, forceupdate: bool = False):
        """Promote live data to "previous" and start a new plot when the action changes.

        Snapshots the current data source under its action UUID, evicts the
        oldest snapshots if more than ``max_prev`` are retained, resets the
        live data, applies axis defaults from :data:`AXIS_MAP` based on the
        new action name, updates the stop-button label/style, and rebuilds
        the plot. Also rebuilds the plot when only the axis selector changed.

        Args:
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
            if self.cur_action_uuid != new_action_uuid or forceupdate:
                LOGGER.info(" ... reseting Gamry graph")
                self.prev_action_uuid = self.cur_action_uuid
                if self.prev_action_uuid != "":
                    self.prev_action_uuids.append(self.prev_action_uuid)
                    LOGGER.info(f"previous uuids: {self.prev_action_uuids}")
                    # copy old data to "prev" plot
                    self.prev_datasources[self.prev_action_uuid] = ColumnDataSource(
                        data=deepcopy(self.datasource.data)
                    )
                self.cur_action_uuid = new_action_uuid
                # update prev_datasources
                while len(self.prev_action_uuids) > self.max_prev:
                    rp = self.prev_action_uuids.pop(0)
                    if rp in self.prev_datasources:
                        self.prev_datasources.pop(rp)
                self.datasource.data = {key: [] for key in self.data_dict_keys}
                if action_name in AXIS_MAP:
                    xlab, ylab = AXIS_MAP[action_name]
                    self.xaxis_selector_group.update(value=xlab)
                    self.yaxis_selector_group.update(value=ylab)
                    self.xselect = self.xaxis_selector_group.value
                    self.yselect = self.yaxis_selector_group.value
                self.button_stop_measure.label = f"Stop {action_name}"
                self.button_stop_measure.button_type = "danger"
                self._add_plots()
        if (self.xselect != self.xaxis_selector_group.value) or (
            self.yselect != self.yaxis_selector_group.value
        ):
            self.xselect = self.xaxis_selector_group.value
            self.yselect = self.yaxis_selector_group.value
            self._add_plots()
