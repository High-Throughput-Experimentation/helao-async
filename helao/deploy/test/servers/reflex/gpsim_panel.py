"""Reflex panel for the GP simulator's live acquisition stream.

Reflex port of ``servers/visualizer/gpsim_live_vis.py``. This payload does not
fit the flat numeric-column model — it carries per-plate sample arrays
(``pred_avail``, ``gt_acquired``) and string columns (``orchestrator``,
``last_acquisition``) — so this panel reads the ingest layer's raw message
deque and its mixed-type row buffer rather than the numeric ring.

Binning is xy's job: raw samples go straight to :func:`plots.histogram`, which
uses xy's native ``hist`` mark.
"""

__all__ = [
    "WS_PATH",
    "STATE_BASE",
    "build",
    "extract_histograms",
    "extract_table_rows",
    "panel_id",
]

import reflex as rx

from helao.core.servers.reflex import plots
from helao.core.servers.reflex.state import LiveVisState

WS_PATH = "ws_live"

#: Histogram range and bin count carried over from gpsim_live_vis.py.
HIST_BINS = 100
HIST_RANGE = (0.2, 0.7)

#: Table columns, matching the Bokeh DataTable.
TABLE_COLUMNS = [
    "plate_id",
    "step",
    "frac_acquired",
    "last_acquisition",
    "orchestrator",
]


def panel_id(server_key: str, session_token: str) -> str:
    """Buffer-store identity for this panel in one browser session.

    Scoped per session: the store holds one frame per key while the version
    counter is per-session state, so a shared key lets two tabs 404 each other
    into a frozen chart.
    """
    return f"gpsim-{server_key}-{session_token}"


def extract_table_rows(ingest) -> list:
    """Pull the acquisition-table rows from the newest raw batch.

    Read from ``ingest.raw`` rather than ``ingest.rows`` because ``normalize``
    classifies each key by float-coercibility: ``plate_id``, ``step`` and
    ``frac_acquired`` are numeric and land in the ring buffer, so only
    ``last_acquisition`` and ``orchestrator`` ever reach ``rows`` -- three of the
    five columns would render permanently blank.

    Args:
        ingest: The panel's :class:`WsIngest`.

    Returns:
        list: One list-of-strings per plate in the newest batch, ordered to
        match :data:`TABLE_COLUMNS`.
    """
    if not ingest.raw:
        return []
    out: list = []
    for message in ingest.raw[-1]:
        if not isinstance(message, dict):
            continue
        values = {}
        for column in TABLE_COLUMNS:
            payload = message.get(column)
            if isinstance(payload, (tuple, list)) and len(payload) == 2:
                values[column] = payload[0]
        plates = values.get("plate_id") or []
        for i in range(len(plates)):
            row = []
            for column in TABLE_COLUMNS:
                seq = values.get(column) or []
                cell = seq[i] if i < len(seq) else ""
                if isinstance(cell, float):
                    cell = f"{cell:.4g}"
                row.append(str(cell))
            out.append(row)
    return out


def extract_histograms(ingest) -> dict:
    """Pull per-plate sample arrays out of the most recent raw batch.

    Args:
        ingest: The panel's :class:`WsIngest`.

    Returns:
        dict: ``{"<plate_id> predicted": [...], "<plate_id> acquired": [...]}``.
            Empty when no usable batch has arrived.
    """
    if not ingest.raw:
        return {}
    out: dict = {}
    for message in ingest.raw[-1]:
        if not isinstance(message, dict):
            continue
        plates = message.get("plate_id")
        pred = message.get("pred_avail")
        acq = message.get("gt_acquired")
        if not (plates and pred and acq):
            continue
        plate_ids, pred_vals, acq_vals = plates[0], pred[0], acq[0]
        for i, plate in enumerate(plate_ids):
            if i < len(pred_vals):
                out[f"{plate} predicted"] = list(pred_vals[i])
            if i < len(acq_vals):
                out[f"{plate} acquired"] = list(acq_vals[i])
    return out


class _State(LiveVisState, mixin=True):
    """Chart binding vars plus the acquisitions table."""

    chart_spec: dict = {}
    chart_url: str = ""
    chart_layout: str = ""
    version: int = 0
    table_rows: list = []
    #: Accumulated per-plate samples. The driver runs plates concurrently and
    #: each pushes its own message, so a single drain batch holds only whichever
    #: plates happened to land in it. The Bokeh original kept a persistent
    #: per-plate dict for the same reason; without it the chart flickers between
    #: plates instead of showing them together.
    hist_samples: dict = {}
    #: message_count at the last table append. extract_table_rows reads the
    #: newest raw batch, but pull() runs on a timer while the driver publishes
    #: per acquisition -- without a watermark the same batch is re-appended
    #: every tick and "Last 20 acquisitions" collapses to one row repeated. The
    #: Bokeh original streamed once per websocket batch, being event-driven.
    last_table_count: int = -1

    def panel_key(self) -> str:
        """Session-scoped buffer-store key; see VisPanelState.panel_key."""
        return panel_id(self.server_key, self.router.session.client_token)

    def pull(self, ingest) -> None:
        """Recompute the histogram payload and the last 20 acquisition rows."""
        self.version += 1
        merged = dict(self.hist_samples)
        merged.update(extract_histograms(ingest))
        self.hist_samples = merged
        payload = plots.histogram(
            merged,
            bins=HIST_BINS,
            value_range=HIST_RANGE,
            x_label="Eta (V vs O2/H2O)",
            y_label="density",
            panel_id=self.panel_key(),
            version=self.version,
        )
        self.chart_spec = payload.spec
        self.chart_url = payload.buffer_url
        self.chart_layout = payload.layout
        count = ingest.status.message_count
        if count != self.last_table_count:
            self.last_table_count = count
            self.table_rows = (self.table_rows + extract_table_rows(ingest))[-20:]


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
                rx.heading(f"GP simulator: {server_key}", size="3"),
                rx.badge(state_cls.connection),
                rx.spacer(),
                rx.input(
                    default_value=state_cls.update_rate.to_string(),
                    on_blur=state_cls.on_update_rate,
                    placeholder="update sec",
                    width="8em",
                ),
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
            rx.heading("Last 20 acquisitions across all orchestrators", size="2"),
            rx.data_table(
                data=state_cls.table_rows,
                columns=TABLE_COLUMNS,
                pagination=False,
                search=False,
                sort=False,
            ),
            width="100%",
            spacing="3",
            on_mount=state_cls.render_loop,
            on_unmount=state_cls.stop_loop,
        ),
        width="100%",
    )
