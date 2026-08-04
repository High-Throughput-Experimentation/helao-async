"""Reflex panel for a spectrometer's per-action spectra.

Reflex port of ``servers/visualizer/spec_vis.py``: the most recent spectrum of
the running action beside the previous action's last one.

The wavelength axis is not in the data stream -- the Bokeh panel fetches it
from the action server at startup -- so this fetches it once in the background
and plots against the detector channel index until it arrives.
"""

__all__ = ["WS_PATH", "STATE_BASE", "build", "panel_id"]

import numpy as np
import reflex as rx

from helao.core.servers.reflex import plots
from helao.core.servers.reflex.state import ActionVisState
from helao.deploy.hte.servers.reflex._action import latest_action_uuid
from helao.deploy.hte.servers.reflex._spectra import (
    channel_columns,
    downsample,
    latest_spectrum,
    spectrum_axis,
)

WS_PATH = "ws_data"

#: Stride applied to the spectrum before plotting, matching the Bokeh default.
DOWNSAMPLE = 2


def panel_id(server_key: str, session_token: str) -> str:
    """Buffer-store identity for this panel in one browser session."""
    return f"spec-{server_key}-{session_token}"


class _State(ActionVisState, mixin=True):
    """The current spectrum plus the wavelength axis, once it is known."""

    chart_spec: dict = {}
    chart_url: str = ""
    chart_layout: str = ""
    version: int = 0
    action_uuid: str = ""
    axis_label: str = "Detector channel"
    #: Wavelengths fetched from the action server. Empty until they arrive,
    #: and empty forever on a server that does not answer -- the panel plots
    #: against the channel index in that case rather than not plotting.
    _wavelengths: list = []
    _fetch_attempted: bool = False

    def panel_key(self) -> str:
        """Session-scoped buffer-store key; see VisPanelState.panel_key."""
        return panel_id(self.server_key, self.router.session.client_token)

    @rx.event(background=True)
    async def load_wavelengths(self):
        """Ask the action server for its wavelength axis, once.

        Background because it is an HTTP round trip, and guarded because a
        server without the endpoint must be asked once rather than on every
        tick.
        """
        async with self:
            if self._fetch_attempted:
                return
            self._fetch_attempted = True
            server_key = self.server_key
        from helao.core.error import ErrorCodes
        from helao.helpers.config_loader import CONFIG
        from helao.helpers.dispatcher import async_private_dispatcher

        server = ((CONFIG or {}).get("servers") or {}).get(server_key) or {}
        host, port = server.get("host"), server.get("port")
        if not host or not port:
            return
        try:
            response, error = await async_private_dispatcher(
                server_key, host, port, "get_wl", {}, {}
            )
        except Exception:
            return
        if error != ErrorCodes.none or not isinstance(response, list):
            return
        async with self:
            self._wavelengths = [float(v) for v in response]

    def pull(self, ingest) -> None:
        """Recompute the spectrum from the most recent packet."""
        snapshot = ingest.buffer.snapshot(self.window_points)
        spectrum = latest_spectrum(snapshot)
        x, label = spectrum_axis(self._wavelengths, len(channel_columns(snapshot)))
        if spectrum.size != x.size:
            # A packet mid-write can leave the two disagreeing; skip the frame
            # rather than let plots raise from inside the render.
            return
        x, spectrum = downsample(x, spectrum, DOWNSAMPLE)
        self.axis_label = label
        self.version += 1
        payload = plots.time_series(
            x,
            {"transmittance": spectrum} if spectrum.size else {},
            x_label=label,
            y_label="Transmittance (counts/s)",
            x_is_epoch=False,
            panel_id=self.panel_key(),
            version=self.version,
        )
        self.chart_spec = payload.spec
        self.chart_url = payload.buffer_url
        self.chart_layout = payload.layout
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
                rx.heading(f"Spectra: {server_key}", size="4"),
                rx.badge(state_cls.connection),
                rx.spacer(),
                rx.text(state_cls.axis_label, size="1", class_name="text-slate-500"),
                rx.text(state_cls.action_uuid, size="1", class_name="text-slate-500"),
                width="100%",
                align="center",
                spacing="3",
            ),
            rx.cond(
                state_cls.error != "",
                rx.text(state_cls.error, class_name="text-red-600"),
            ),
            plots.chart(
                state_cls.chart_spec,
                state_cls.chart_url,
                state_cls.chart_layout,
                height=320,
            ),
            width="100%",
            spacing="3",
            on_mount=[state_cls.render_loop, state_cls.load_wavelengths],
            on_unmount=state_cls.stop_loop,
        ),
        width="100%",
    )
