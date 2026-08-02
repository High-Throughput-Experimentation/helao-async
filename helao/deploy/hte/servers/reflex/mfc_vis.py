"""Reflex panel for a mass-flow controller's live datastream.

Reflex port of ``servers/visualizer/mfc_vis.py``. Columns arrive as
``{device}__{field}``; the Bokeh panel means the flow and pressure fields, so
this matches on those suffixes rather than on a device list -- which keeps it
correct for a station with any number of controllers.
"""

__all__ = ["WS_PATH", "STATE_BASE", "Y_LABEL", "build", "panel_id"]

from helao.deploy.hte.servers.reflex._live import make_live_panel, suffix_matcher

WS_PATH = "ws_live"
Y_LABEL = "Flow rate (sccm)"

STATE_BASE, build, panel_id = make_live_panel(
    "mfc", Y_LABEL, wants_mean=suffix_matcher("__mass_flow", "__pressure")
)
