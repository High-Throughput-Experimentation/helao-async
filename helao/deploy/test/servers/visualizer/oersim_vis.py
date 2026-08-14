"""Bokeh visualizer module for the OER CP simulator action server.

Subscribes to a CP simulator's ``ws_data`` websocket and renders the
in-flight CP trace alongside the previous trace as the action UUID
changes.
"""

from copy import deepcopy
from functools import partial

from bokeh.layouts import Spacer, layout
from bokeh.models import (
    ColumnDataSource,
    TextInput,
)
from bokeh.models.widgets import Div
from bokeh.plotting import figure

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.core.models.hlostatus import HloStatus
from helao.ui.shared.palette import PANEL_BG, SERIES, panel_styles
from helao.ui.bokeh.theme import SECTION_MARGIN, stretch_section
from helao.core.servers.vis import Vis
from helao.core.servers.vis_subscriber import ActionVisualizer

VALID_DATA_STATUS = (
    None,
    "active",
    HloStatus.active,
)

VALID_ACTION_NAME = ("measure_cp",)


class C_vis(ActionVisualizer):
    """Live OER CP visualizer for the CP simulator action server.

    Subscribes to the action server's ``ws_data`` websocket and maintains
    a "current" plot for the in-flight trace plus a "previous" plot
    holding the most recent prior action's trace, switching whenever the
    streamed ``action_uuid`` changes. Common subscriber bring-up, the
    ``max datapoints`` callback, and the ingest loop are inherited from
    :class:`ActionVisualizer`.

    Attributes:
        datasource: ``ColumnDataSource`` backing the live plot.
        prev_datasources: Per-uuid snapshots backing the previous plot.
        cur_action_uuid: Currently-streamed action UUID.
        cur_comp: Currently-streamed composition string.
        layout: Top-level Bokeh layout.
    """

    SUBSCRIBE_LABEL = "OER CP simulator visualizer"

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Build the layout and start the websocket polling task.

        Args:
            vis_serv: Hosting visualizer server.
            serv_key: Name of the action server to visualize.
        """
        super().__init__(vis_serv, serv_key)
        if not self.connected:
            return
        actserv_host = self.host
        actserv_port = self.port

        self.data_dict_keys = ["t_s", "erhe_v"]
        self.datasource = ColumnDataSource(
            data={key: [] for key in self.data_dict_keys}
        )
        self.cur_action_uuid = ""
        self.cur_comp = ""

        # prev_datasources aren't streamed, replot when axis or action_uuid changes
        self.prev_datasources = {}
        self.prev_action_uuid = ""
        self.prev_comp = ""
        self.prev_action_uuids = []

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

        self.plot = figure(title="Title", height=300, sizing_mode="stretch_width")
        self.plot_prev = figure(title="Title", height=300, sizing_mode="stretch_width")
        self.plot.xaxis.axis_label = "Time (seconds)"
        self.plot.yaxis.axis_label = "E vs RHE (V)"
        self.plot_prev.xaxis.axis_label = "Time (seconds)"
        self.plot_prev.yaxis.axis_label = "E vs RHE (V)"

        # combine all sublayouts into a single one
        docs_url = f"http://{actserv_host}:{actserv_port}/docs#/"
        server_link = f'<a href="{docs_url}" target="_blank">\'{self.serv_key}\'</a>'
        headerbar = f"<b>OER CP simulator for server {server_link}</b>"
        self.layout = layout(
            [
                [
                    Spacer(width=20),
                    Div(text=headerbar, sizing_mode="stretch_width", height=15),
                ],
                [
                    self.input_max_points,
                ],
                Spacer(height=10),
                [self.plot, Spacer(width=20), self.plot_prev],
                Spacer(height=10),
            ],
            styles=panel_styles(PANEL_BG),
            margin=SECTION_MARGIN,
        )
        stretch_section(self.layout)

        self._mount()
        self.reset_plot(self.cur_action_uuid, forceupdate=True)

    def add_points(self, datapackage_list: list):
        """Stream a batch of websocket data packages into the live plot.

        Resets to a new ``action_uuid`` when one appears, accumulates
        ``t_s``/``erhe_v`` samples, derives a composition string from
        ``elements``/``atfracs``, pads short series with ``"NaN"``, and
        streams the result into the datasource with rollover.

        Args:
            datapackage_list: List of data packages from the websocket.
        """
        for data_package in datapackage_list:
            data_dict = {k: [] for k in self.data_dict_keys}
            if (
                data_package.datamodel.status in VALID_DATA_STATUS
                and data_package.action_name in VALID_ACTION_NAME
            ):
                # only resets if axis selector or action_uuid changes
                self.reset_plot(str(data_package.action_uuid))
                for _, uuid_dict in data_package.datamodel.data.items():
                    for data_label, data_val in uuid_dict.items():
                        if data_label in self.data_dict_keys:
                            if isinstance(data_val, list):
                                data_dict[data_label] += data_val
                            else:
                                data_dict[data_label].append(data_val)
                        elif data_label == "elements":
                            compstr = "-".join(
                                [
                                    f"{x}{y:.2f}"
                                    for x, y in zip(data_val, uuid_dict["atfracs"])
                                ]
                            )
                            if self.cur_comp != compstr:
                                self.cur_comp = compstr
                                self._add_plots()

            # check for missing I_A in OCV
            max_len = max([len(v) for v in data_dict.values()])
            for k, v in data_dict.items():
                if len(v) < max_len:
                    pad_len = max_len - len(v)
                    data_dict[k] += ["NaN"] * pad_len
            self.datasource.stream(data_dict, rollover=self.max_points)

    def _add_plots(self):
        """Redraw the current and previous CP plots from cached datasources."""
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
        colors = [SERIES[0], SERIES[1], SERIES[3], SERIES[2]]
        self.plot.line(
            x="t_s",
            y="erhe_v",
            line_color=colors[0],
            source=self.datasource,
            name=self.cur_action_uuid,
            legend_label=self.cur_comp,
        )
        self.plot.legend.location = "bottom_right"
        for puuid in self.prev_action_uuids:
            self.plot_prev.line(
                x="t_s",
                y="erhe_v",
                line_color=colors[1],
                source=self.prev_datasources[puuid],
                name=puuid,
                legend_label=self.prev_comp,
            )
            self.plot_prev.legend.location = "bottom_right"

    def reset_plot(self, new_action_uuid=None, forceupdate: bool = False):
        """Move the active trace to the "previous" plot when the UUID changes.

        Args:
            new_action_uuid: UUID of the newly active action.
            forceupdate: If True, redraw even when the UUID has not changed.
        """
        if self.cur_action_uuid != new_action_uuid or forceupdate:
            if new_action_uuid is not None:
                LOGGER.info(" ... reseting CP graph")
                self.prev_action_uuid = self.cur_action_uuid
                self.prev_comp = self.cur_comp
                if self.prev_action_uuid != "":
                    self.prev_action_uuids.append(self.prev_action_uuid)
                    LOGGER.info(f"previous uuids: {self.prev_action_uuids}")
                    # copy old data to "prev" plot
                    self.prev_datasources[self.prev_action_uuid] = ColumnDataSource(
                        data=deepcopy(self.datasource.data)
                    )
                self.cur_action_uuid = new_action_uuid
                # update prev_datasources
                while len(self.prev_action_uuids) > 1:
                    rp = self.prev_action_uuids.pop(0)
                    self.prev_datasources.pop(rp)
                self.datasource.data = {key: [] for key in self.data_dict_keys}
            self._add_plots()
