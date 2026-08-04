from copy import deepcopy
from datetime import datetime
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
from helao.core.servers.palette import PANEL_BG, panel_styles, red_ramp
from helao.core.servers.bokeh_theme import SECTION_MARGIN, stretch_section
from helao.core.servers.vis import Vis
from helao.core.servers.vis_subscriber import ActionVisualizer
from helao.helpers.dispatcher import private_dispatcher

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


class C_vis(ActionVisualizer):
    """Bokeh visualizer for a spectrometer action server.

    Subscribes to the server's ``ws_data`` WebSocket and renders the active
    action's spectra plus a snapshot of the previous action's spectra side
    by side. Wavelength and energy axes are fetched once from the action
    server via :func:`private_dispatcher`; the displayed traces fade across
    a configurable colormap as new spectra are appended. Common subscriber
    bring-up and the ingest loop are inherited from :class:`ActionVisualizer`.

    Attributes:
        max_spectra: Maximum number of spectra retained per action.
        downsample: Stride applied to ``wl``, ``ev``, and ``trans`` data.
        _ramp: Recency-shading swatches from
            :func:`~helao.core.servers.palette.red_ramp`, one per retained
            spectrum, used to colour individual spectra.
        latest_coloridx: Reserved counter for the newest spectrum's colour.
        wl: Wavelength axis fetched from the action server.
        ev: Energy axis derived from ``wl``.
        data_dict_keys: Column names streamed per spectrum.
        datasource: Live :class:`ColumnDataSource` for the current action.
        prev_datasource: Snapshotted source for the previous action.
        cur_action_uuid: Action UUID currently being plotted.
        prev_action_uuid: Action UUID of the previous run.
        layout: Composed Bokeh layout mounted on the document.
        input_max_spectra: Widget setting ``max_spectra``.
        input_downsample: Widget setting ``downsample``.
        plot: Active spectra ``figure``.
        plot_prev: Previous spectra ``figure``.
    """

    SUBSCRIBE_LABEL = "spectrometer visualizer"

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Wire up data sources, widgets, plot layout, and start the WS ingest task.

        Args:
            vis_serv: Host :class:`Vis` server providing the Bokeh document.
            serv_key: Configuration key of the spectrometer action server.
                If the server is not in the config, ``__init__`` returns
                early without registering any roots.
        """
        super().__init__(vis_serv, serv_key)
        if not self.connected:
            return
        self.max_spectra = 5
        self.downsample = 2

        self._ramp = red_ramp(self.max_spectra)
        self.latest_coloridx = 0

        self.wl = private_dispatcher(
            self.serv_key,
            self.host,
            self.port,
            "get_wl",
            params_dict={},
            json_dict={},
        )[0]
        LOGGER.info(self.wl)
        self.ev = [1239.8 / x for x in self.wl]

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

        self.plot = figure(title="Title", height=300, sizing_mode="stretch_width")
        self.plot.xaxis.axis_label = "Wavelength (nm)"
        self.plot.yaxis.axis_label = "Transmittance (counts/sec)"

        self.plot_prev = figure(title="Title", height=300, sizing_mode="stretch_width")
        self.plot_prev.xaxis.axis_label = "Wavelength (nm)"
        self.plot_prev.yaxis.axis_label = "Transmittance (counts/sec)"
        # combine all sublayouts into a single one
        docs_url = f"http://{self.host}:{self.port}/docs#/"
        server_link = f'<a href="{docs_url}" target="_blank">\'{self.serv_key}\'</a>'
        headerbar = f"<b>Spectrometer Visualizer module for server {server_link}</b>"
        self.layout = layout(
            [
                [
                    Spacer(width=20),
                    Div(text=headerbar, sizing_mode="stretch_width", height=15),
                ],
                [self.input_max_spectra, Spacer(width=20), self.input_downsample],
                Spacer(height=10),
                [self.plot, Spacer(width=20), self.plot_prev],
                Spacer(height=10),
            ],
            styles=panel_styles(PANEL_BG),
            margin=SECTION_MARGIN,
        )
        stretch_section(self.layout)

        # to check if selection changed during ploting
        # self.xselect = self.xaxis_selector_group.active
        # self.yselect = self.yaxis_selector_group.active
        # self._add_plots()

        self._mount()
        self.reset_plot(self.cur_action_uuid, forceupdate=True)

    def callback_input_max_spectra(self, attr, old, new, sender):
        """Validate the ``max num spectra`` input and resize the colour ramp.

        Parses ``new`` as an int, falls back to ``old`` (or ``500``) on bad
        input, then clamps to ``[2, 10000]`` before storing it as
        ``self.max_spectra``, regenerating the red recency ramp, and
        refreshing the widget.

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

        self.max_spectra = newpts
        self._ramp = red_ramp(self.max_spectra)

        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.max_spectra}")
        )

    def callback_input_downsample(self, attr, old, new, sender):
        """Validate the ``downsampling factor`` input.

        Parses ``new`` as an int (defaulting to ``old`` or ``2``), stores it
        as ``self.downsample``, and writes the value back to the widget.

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
                newpts = 2
        self.downsample = newpts

        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.downsample}")
        )

    def add_points(self, datapackage_list: list):
        """Append new spectra to the live source and roll older colours.

        Promotes prior data to the previous-action source when the action
        UUID changes, then for each accepted package builds a downsampled
        ``wl``/``ev``/``trans`` row, "patches" existing colour entries to
        fade older spectra, and streams the new row into ``self.datasource``.

        Args:
            datapackage_list: List of data packages from the WebSocket.
        """
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
                        "color": [self._ramp[0]],
                        "time": [dtstr],
                    }

                    current_colors = self.datasource.data["color"]
                    new_colors = [
                        self._ramp[(i + 1) % self.max_spectra]
                        for i, _ in enumerate(current_colors)
                    ]
                    self.datasource.patch(
                        {"color": [(slice(len(new_colors)), new_colors)]}
                    )
                    self.datasource.stream(data_dict, rollover=self.max_spectra)

    def _add_plots(self):
        """Rebuild the active and previous spectra figures with current sources."""
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
        """Snapshot the live spectra to the previous-action figure on UUID change.

        When the action UUID changes (or ``forceupdate`` is set), the live
        data is deep-copied to ``prev_datasource``, ``cur_action_uuid`` is
        updated, the live data is cleared, and both figures are rebuilt.

        Args:
            new_action_uuid: Action UUID of the incoming data package.
            forceupdate: If ``True``, force a rebuild even when the UUID
                hasn't changed.
        """
        if self.cur_action_uuid != new_action_uuid or forceupdate:
            if new_action_uuid is not None:
                LOGGER.info(" ... reseting spectrometer graph")
                self.prev_action_uuid = self.cur_action_uuid
                self.prev_datasource.data = dict(deepcopy(self.datasource.data).items())
                self.cur_action_uuid = new_action_uuid
                self.datasource.data = {key: [] for key in self.data_dict_keys}
            self._add_plots()
