"""Reflex panel for a pressure sensor's live datastream.

Reflex port of ``servers/visualizer/pressure_vis.py``. Every analog input gets
a rolling-mean partner, as it does there.
"""

__all__ = ["WS_PATH", "STATE_BASE", "Y_LABEL", "build", "panel_id"]

from helao.deploy.hte.servers.reflex._live import every_column, make_live_panel

WS_PATH = "ws_live"
Y_LABEL = "Pressure (psi)"

STATE_BASE, build, panel_id = make_live_panel(
    "pressure", Y_LABEL, wants_mean=every_column
)
