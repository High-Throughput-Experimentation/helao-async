"""Reflex panel for the GP simulator's live acquisition stream.

Reflex port of ``servers/visualizer/gpsim_live_vis.py``. This payload does not
fit the flat numeric-column model — it carries per-plate sample arrays
(``pred_avail``, ``gt_acquired``) and string columns (``orchestrator``,
``last_acquisition``) — so this panel reads the ingest layer's raw message
deque and its mixed-type row buffer rather than the numeric ring.

Binning is xy's job: raw samples go straight to :func:`plots.histogram`, which
uses xy's native ``hist`` mark.
"""

__all__ = ["WS_PATH", "STATE_BASE", "build", "extract_histograms", "panel_id"]

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


def panel_id(server_key: str) -> str:
    """Stable buffer-store identity for this panel."""
    return f"gpsim-{server_key}"


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


class _State(LiveVisState):
    """Chart binding vars plus the acquisitions table."""

    chart_spec: dict = {}
    chart_url: str = ""
    version: int = 0
    table_rows: list = []

    def pull(self, ingest) -> None:
        """Recompute the histogram payload and the last 20 acquisition rows."""
        self.version += 1
        payload = plots.histogram(
            extract_histograms(ingest),
            bins=HIST_BINS,
            value_range=HIST_RANGE,
            x_label="Eta (V vs O2/H2O)",
            y_label="density",
            panel_id=panel_id(self.server_key_default),
            version=self.version,
        )
        self.chart_spec = payload.spec
        self.chart_url = payload.buffer_url
        self.table_rows = [
            [str(row.get(col, "")) for col in TABLE_COLUMNS]
            for row in ingest.rows.rows()[-20:]
        ]


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
                rx.heading(f"GP simulator: {server_key}", size="4"),
                rx.badge(state_cls.connection),
                rx.spacer(),
                rx.input(
                    default_value=str(state_cls.update_rate),
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
                rx.text(state_cls.error, color_scheme="red"),
            ),
            plots.chart(state_cls.chart_spec, state_cls.chart_url, height=320),
            rx.heading("Last 20 acquisitions across all orchestrators", size="3"),
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
