"""Reflex panel for an OceanDirect spectrometer's per-action spectra.

Reflex counterpart of ``servers/visualizer/oceandirect_vis.py``, resolving from
the same ``action_vis: oceandirect_vis`` config key — a station gains this panel
by adding a ``reflex:`` server and changing nothing else.

Unlike ``spec_vis`` next door, this needs no background fetch of the wavelength
axis: the OceanDirect server streams ``wl`` as a column, so the x axis arrives
with the data. Reframing long-format rows into whole spectra is
``servers/spec_long_format.py``, shared with the Bokeh panel.

**All spectra go in one chart.** Each chart is a WebGL canvas and browsers cap
how many contexts may be live (Chrome: 16), after which the oldest is evicted
and stops drawing permanently while every other signal still reads healthy. So
the recent spectra are traces on a single chart rather than a chart apiece.
"""

__all__ = ["WS_PATH", "STATE_BASE", "build", "panel_id"]

import numpy as np
import reflex as rx

from helao.deploy.hte.servers.reflex._action import MUTED_TEXT, latest_action_uuid
from helao.deploy.hte.servers.spec_long_format import (
    INTENSITY_COLUMN,
    WAVELENGTH_COLUMN,
    latest_spectra,
)
from helao.ui.reflex import plots
from helao.ui.reflex.state import ActionVisState

WS_PATH = "ws_data"

#: Spectra drawn at once, newest first. Small on purpose: each is a trace, and
#: the point of the panel is the current spectrum against its predecessors.
MAX_SPECTRA = 3

#: Stride applied before plotting, matching the Bokeh panel's default. A 2048
#: pixel detector at stride 2 is 1024 points per trace.
DOWNSAMPLE = 2

#: Trailing rows this panel reads per render.
#:
#: Used instead of the inherited ``window_points`` var, which every other panel
#: treats as an operator control, because a *row* in the long format is one
#: pixel rather than one acquisition — "1000 points" means half a spectrum
#: here, so exposing it would be actively misleading. 16384 holds two whole
#: spectra even for an 8192-pixel detector and eight for a 2048-pixel one,
#: which is more than :data:`MAX_SPECTRA` needs, while sparing every tick a
#: scan of the million-row buffer it would immediately discard.
WINDOW_POINTS = 16384


def panel_id(server_key: str, session_token: str) -> str:
    """Buffer-store identity for this panel in one browser session."""
    return f"odspec-{server_key}-{session_token}"


class _State(ActionVisState, mixin=True):
    """The most recent spectra of the running action.

    A mixin, not a concrete state: a var declared on a concrete ``rx.State``
    is owned by that class and shared by every substate under it, so two
    panels on a page would share one ``chart_spec``.
    """

    chart_spec: dict = {}
    chart_url: str = ""
    chart_layout: str = ""
    version: int = 0
    action_uuid: str = ""
    #: Header readout: frame numbers currently drawn, newest first.
    frames: str = ""

    def panel_key(self) -> str:
        """Session-scoped buffer-store key; see VisPanelState.panel_key."""
        return panel_id(self.server_key, self.router.session.client_token)

    def pull(self, ingest) -> None:
        """Reframe the window into spectra and republish the chart."""
        snapshot = ingest.buffer.snapshot(WINDOW_POINTS)
        spectra = latest_spectra(snapshot, max_spectra=MAX_SPECTRA)

        step = max(1, DOWNSAMPLE)
        series: dict = {}
        x = np.empty(0, dtype=float)
        for position, spectrum in enumerate(spectra):
            wl = spectrum[WAVELENGTH_COLUMN][::step]
            intensity = spectrum[INTENSITY_COLUMN][::step]
            if position == 0:
                x = wl
            elif wl.size != x.size:
                # Every spectrum from one device shares a wavelength axis, so
                # this only happens if the pixel count changed mid-window (a
                # reconnect to a different device). Skip the stragglers rather
                # than let plots raise from inside the render.
                continue
            label = "latest" if position == 0 else f"-{position}"
            series[label] = intensity

        self.version += 1
        payload = plots.spectra(
            x,
            series,
            x_label="Wavelength (nm)",
            y_label="Intensity (counts)",
            panel_id=self.panel_key(),
            version=self.version,
        )
        self.chart_spec = payload.spec
        self.chart_url = payload.buffer_url
        self.chart_layout = payload.layout
        self.frames = ", ".join(str(s["frame"]) for s in spectra)
        self.action_uuid = latest_action_uuid(ingest)


STATE_BASE = _State


def build(server_key: str, state_cls):
    """Render the panel.

    Args:
        server_key: Action server this panel reads.
        state_cls: Generated state class bound to ``server_key``.

    Returns:
        rx.Component: The panel card.
    """
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading(f"Spectra: {server_key}", size="3"),
                rx.badge(state_cls.connection),
                rx.spacer(),
                # Concatenation, not an f-string: an f-string over a Var
                # stringifies the Var rather than interpolating its value at
                # render time.
                rx.text(
                    rx.cond(
                        state_cls.frames != "",
                        "frames " + state_cls.frames,
                        "no spectrum yet",
                    ),
                    size="1",
                    class_name=MUTED_TEXT,
                ),
                rx.text(state_cls.action_uuid, size="1", class_name=MUTED_TEXT),
                width="100%",
                align="center",
                spacing="3",
            ),
            rx.cond(
                state_cls.error != "",
                rx.text(state_cls.error, class_name="text-red-600"),
            ),
            # One chart for every spectrum: see the WebGL note in the module
            # docstring. A chart per spectrum would cost MAX_SPECTRA contexts.
            plots.chart(
                state_cls.chart_spec,
                state_cls.chart_url,
                state_cls.chart_layout,
                height=320,
            ),
            width="100%",
            spacing="3",
            on_mount=state_cls.render_loop,
            on_unmount=state_cls.stop_loop,
        ),
        width="100%",
    )
