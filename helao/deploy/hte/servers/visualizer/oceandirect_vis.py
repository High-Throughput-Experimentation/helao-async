"""Bokeh visualizer for an OceanDirect spectrometer action server.

Sibling of ``spec_vis.py``, which serves the SM303. The two differ in exactly
one respect that matters here: the SM303 streams a spectrum *wide* (one
``ch_NNNN`` column per channel) and fetches its wavelength axis from the action
server at startup, while the OceanDirect server streams it *long* — five
columns where a spectrum occupies ``n_pixels`` consecutive rows keyed by
``spec_idx``, wavelengths included. So this panel does no ``/get_wl`` round
trip and never plots against a bare channel index: reframing is grouping rows
by ``spec_idx``, which ``servers/spec_long_format.py`` does for both UI stacks.

Layout follows ``spec_vis``: the running action's recent spectra on the left,
the previous action's snapshot on the right, older traces faded through the
palette's red recency ramp.
"""

# Only ``C_vis``: a panel module is not a Bokeh app. ``action_visualizer``'s
# ``mount_visualizers`` imports this module by the ``action_vis`` config key and
# instantiates ``C_vis(vis_serv=..., serv_key=...)``; a ``makeBokehApp`` here
# would never be called.
__all__ = ["C_vis"]

from copy import deepcopy
from datetime import datetime
from functools import partial

from bokeh.layouts import Spacer, layout
from bokeh.models import ColumnDataSource, TextInput
from bokeh.models.widgets import Div
from bokeh.plotting import figure

from helao.core.models.hlostatus import HloStatus
from helao.deploy.hte.servers.spec_long_format import (
    EPOCH_COLUMN,
    INTENSITY_COLUMN,
    WAVELENGTH_COLUMN,
    latest_spectra,
)
from helao.helpers import helao_logging as logging
from helao.ui.bokeh.theme import SECTION_MARGIN, stretch_section
from helao.ui.bokeh.vis import Vis
from helao.ui.bokeh.vis_subscriber import ActionVisualizer
from helao.ui.shared.palette import PANEL_BG, panel_styles, red_ramp

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

VALID_DATA_STATUS = (
    None,
    "active",
    HloStatus.active,
)

#: Action names that stream spectra. The device-control actions on the same
#: server (``set_tec``, ``set_shutter``, ...) publish a status dict, not a
#: spectrum, so a panel that accepted every action name would try to reframe
#: a payload with no ``spec_idx`` in it.
VALID_ACTION_NAME = (
    "acquire_spec",
    "acquire_spec_adv",
    "acquire_spec_corrected",
    "acquire_spec_buffered",
    "calibrate_intensity",
)


class C_vis(ActionVisualizer):
    """Bokeh visualizer for an OceanDirect spectrometer action server.

    Subscribes to the server's ``ws_data`` WebSocket and renders the running
    action's spectra beside a snapshot of the previous action's. Common
    subscriber bring-up and the ingest loop come from
    :class:`~helao.ui.bokeh.vis_subscriber.ActionVisualizer`.

    Attributes:
        max_spectra: Spectra retained per action.
        downsample: Stride applied to each spectrum before plotting.
        datasource: Live :class:`ColumnDataSource` for the current action.
        prev_datasource: Snapshotted source for the previous action.
        cur_action_uuid: Action UUID currently plotted.
        prev_action_uuid: Action UUID of the previous run.
    """

    SUBSCRIBE_LABEL = "OceanDirect spectrometer visualizer"

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Wire up sources, widgets and plots, then start the WS ingest task.

        Args:
            vis_serv: Host :class:`Vis` server providing the Bokeh document.
            serv_key: Configuration key of the spectrometer action server. If
                the server is absent from the config, ``__init__`` returns
                early without registering any roots.
        """
        super().__init__(vis_serv, serv_key)
        if not self.connected:
            return
        self.max_spectra = 5
        self.downsample = 2

        self._ramp = red_ramp(self.max_spectra)

        self.data_dict_keys = ["wl", "intensity", "color", "time", "frame"]
        self.datasource = ColumnDataSource(
            data={key: [] for key in self.data_dict_keys}
        )
        self.prev_datasource = ColumnDataSource(
            data={key: [] for key in self.data_dict_keys}
        )

        self.cur_action_uuid = ""
        self.prev_action_uuid = ""

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

        self.plot = figure(title="Title", height=300, sizing_mode="stretch_width")
        self.plot.xaxis.axis_label = "Wavelength (nm)"
        self.plot.yaxis.axis_label = "Intensity (counts)"

        self.plot_prev = figure(title="Title", height=300, sizing_mode="stretch_width")
        self.plot_prev.xaxis.axis_label = "Wavelength (nm)"
        self.plot_prev.yaxis.axis_label = "Intensity (counts)"

        docs_url = f"http://{self.host}:{self.port}/docs#/"
        server_link = f'<a href="{docs_url}" target="_blank">\'{self.serv_key}\'</a>'
        headerbar = (
            f"<b>OceanDirect Spectrometer Visualizer module for server "
            f"{server_link}</b>"
        )
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

        self._mount()
        self.reset_plot(self.cur_action_uuid, forceupdate=True)

    def callback_input_max_spectra(self, attr, old, new, sender):
        """Validate the ``max num spectra`` input and resize the colour ramp.

        Args:
            attr: Bokeh property name that changed.
            old: Prior text value.
            new: New text value typed by the user.
            sender: The :class:`TextInput` to refresh.
        """
        newpts = _to_int(new)
        oldpts = _to_int(old)
        if newpts is None:
            newpts = oldpts if oldpts is not None else 5
        newpts = max(2, min(10000, newpts))

        self.max_spectra = newpts
        self._ramp = red_ramp(self.max_spectra)

        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.max_spectra}")
        )

    def callback_input_downsample(self, attr, old, new, sender):
        """Validate the ``downsampling factor`` input.

        Args:
            attr: Bokeh property name that changed.
            old: Prior text value.
            new: New text value typed by the user.
            sender: The :class:`TextInput` to refresh.
        """
        newpts = _to_int(new)
        oldpts = _to_int(old)
        if newpts is None:
            newpts = oldpts if oldpts is not None else 2
        # Clamped at 1, not 0: a stride of 0 empties every trace, and this is
        # a free-text field.
        self.downsample = max(1, newpts)

        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.downsample}")
        )

    def add_points(self, datapackage_list: list):
        """Reframe incoming packets into spectra and stream them.

        A single packet can carry many spectra: the buffered-capture path
        drains up to 15 per read and emits them in one payload. Each is
        streamed as its own ``multi_line`` row, oldest first, so the recency
        ramp reads correctly.

        Args:
            datapackage_list: Data packages from the WebSocket.
        """
        for data_package in datapackage_list:
            # Only resets when the action_uuid changes.
            self.reset_plot(str(data_package.action_uuid))
            if data_package.datamodel.status not in VALID_DATA_STATUS:
                continue
            if data_package.action_name not in VALID_ACTION_NAME:
                continue
            for _, uuid_dict in data_package.datamodel.data.items():
                # Newest-first from the helper; reversed so the stream order
                # below is oldest-first and the newest ends up at ramp[0].
                spectra = latest_spectra(uuid_dict, max_spectra=self.max_spectra)
                for spectrum in reversed(spectra):
                    wl = spectrum[WAVELENGTH_COLUMN][:: self.downsample]
                    intensity = spectrum[INTENSITY_COLUMN][:: self.downsample]
                    data_dict = {
                        "wl": [list(wl)],
                        "intensity": [list(intensity)],
                        "color": [self._ramp[0]],
                        # Per spectrum, not per packet: a buffered drain
                        # carries up to 15 spectra and they are not simultaneous.
                        "time": [_epoch_label(spectrum[EPOCH_COLUMN])],
                        "frame": [spectrum["frame"]],
                    }
                    # Fade what is already plotted before adding the new trace,
                    # so the newest always holds ramp[0].
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
        """Rebuild both figures against the current sources."""
        self.plot.renderers = []
        self.plot_prev.renderers = []

        self.plot.title.text = f"active action_uuid: {self.cur_action_uuid}"
        self.plot_prev.title.text = f"previous action_uuid: {self.prev_action_uuid}"

        self.plot.multi_line(
            xs="wl",
            ys="intensity",
            color="color",
            source=self.datasource,
            name=self.cur_action_uuid,
        )
        self.plot_prev.multi_line(
            xs="wl",
            ys="intensity",
            color="color",
            source=self.prev_datasource,
            name=self.prev_action_uuid,
        )

    def reset_plot(self, new_action_uuid=None, forceupdate: bool = False):
        """Snapshot the live spectra to the previous figure on a UUID change.

        Args:
            new_action_uuid: Action UUID of the incoming data package.
            forceupdate: Force a rebuild even when the UUID is unchanged.
        """
        if self.cur_action_uuid != new_action_uuid or forceupdate:
            if new_action_uuid is not None:
                LOGGER.info(" ... resetting OceanDirect spectrometer graph")
                self.prev_action_uuid = self.cur_action_uuid
                self.prev_datasource.data = dict(deepcopy(self.datasource.data).items())
                self.cur_action_uuid = new_action_uuid
                self.datasource.data = {key: [] for key in self.data_dict_keys}
            self._add_plots()


def _to_int(value):
    """Parse ``value`` as an int, or ``None`` when it will not parse."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _epoch_label(epoch) -> str:
    """Format one spectrum's acquisition time for the trace tooltip.

    ``latest_spectra`` reduces the long format's per-pixel ``epoch_s`` column
    to one value per frame, so a scalar is expected here; a sequence is still
    tolerated, and a missing or unparseable value yields an empty label rather
    than raising inside the ingest loop.
    """
    if isinstance(epoch, (list, tuple)):
        epoch = epoch[0] if epoch else None
    if epoch is None:
        return ""
    try:
        return datetime.fromtimestamp(float(epoch)).strftime("%Y-%m-%d %H:%M:%S.%f")
    except (TypeError, ValueError, OSError):
        return ""
