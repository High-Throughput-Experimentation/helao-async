"""Reflex panel for an Andor camera: first spectrum of the action vs latest.

Pins the first finite spectrum seen for the current ``action_uuid`` in panel
state (so a long acquire cannot push it out of the ring buffer) and overlays
the newest spectrum from the ingest window. One chart, two traces.

Wavelengths are not on the wire -- fetch ``/get_wl`` once on mount, same as
``spec_vis``. Until that lands (or if length disagrees with ``ch_*`` count),
the x axis is detector channel.
"""

__all__ = ["WS_PATH", "STATE_BASE", "build", "panel_id"]

import numpy as np
import reflex as rx

from helao.deploy.hte.servers.reflex._action import MUTED_TEXT, latest_action_uuid
from helao.deploy.hte.servers.reflex._spectra import (
    channel_columns,
    downsample,
    latest_spectrum,
    spectrum_axis,
)
from helao.ui.reflex import plots
from helao.ui.reflex.state import ActionVisState

WS_PATH = "ws_data"

DOWNSAMPLE = 2


def panel_id(server_key: str, session_token: str) -> str:
    """Buffer-store identity for this panel in one browser session."""
    return f"andor-{server_key}-{session_token}"


class _State(ActionVisState, mixin=True):
    """First-of-action spectrum pinned beside the live tip."""

    chart_spec: dict = {}
    chart_url: str = ""
    chart_layout: str = ""
    version: int = 0
    action_uuid: str = ""
    axis_label: str = "Detector channel"
    _wavelengths: list = []
    _fetch_attempted: bool = False
    #: Intensity of the first spectrum seen for ``action_uuid``. Cleared when
    #: the streamed action changes. Empty until that first row arrives.
    _first_intensity: list = []
    _pinned_uuid: str = ""

    def panel_key(self) -> str:
        """Session-scoped buffer-store key; see VisPanelState.panel_key."""
        return panel_id(self.server_key, self.router.session.client_token)

    @rx.event(background=True)
    async def load_wavelengths(self):
        """Ask the action server for its wavelength axis, once."""
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
        if error != ErrorCodes.none or not isinstance(response, list) or not response:
            return
        async with self:
            self._wavelengths = [float(v) for v in response]

    def pull(self, ingest) -> None:
        """Pin the first spectrum of this action; always redraw with the latest."""
        uuid = latest_action_uuid(ingest) or ""
        if uuid != self._pinned_uuid:
            self._pinned_uuid = uuid
            self._first_intensity = []

        snapshot = ingest.buffer.snapshot(self.window_points)
        columns = channel_columns(snapshot)
        latest = latest_spectrum(snapshot)
        if not columns or latest.size == 0 or not np.isfinite(latest).any():
            return

        if not self._first_intensity:
            self._first_intensity = [float(v) for v in latest]

        first = np.asarray(self._first_intensity, dtype=float)
        if first.size != latest.size:
            # Pixel count changed mid-session (AOI / reconnect); re-pin.
            self._first_intensity = [float(v) for v in latest]
            first = latest

        x_full, label = spectrum_axis(self._wavelengths, len(columns))
        if latest.size != x_full.size:
            return

        x, first_y = downsample(x_full, first, DOWNSAMPLE)
        _, latest_y = downsample(x_full, latest, DOWNSAMPLE)

        self.axis_label = label
        self.action_uuid = uuid
        self.version += 1
        payload = plots.spectra(
            x,
            {"first": first_y, "latest": latest_y},
            x_label=label,
            y_label="Intensity (counts)",
            panel_id=self.panel_key(),
            version=self.version,
        )
        self.chart_spec = payload.spec
        self.chart_url = payload.buffer_url
        self.chart_layout = payload.layout


STATE_BASE = _State


def build(server_key: str, state_cls):
    """Render the panel card."""
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading(f"Andor: {server_key}", size="3"),
                rx.badge(state_cls.connection),
                rx.spacer(),
                rx.text("first + latest", size="1", class_name=MUTED_TEXT),
                rx.text(state_cls.axis_label, size="1", class_name=MUTED_TEXT),
                rx.text(state_cls.action_uuid, size="1", class_name=MUTED_TEXT),
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
