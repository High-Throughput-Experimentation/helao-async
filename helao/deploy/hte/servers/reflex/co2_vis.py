"""Reflex panel for a CO2 sensor's live datastream.

Reflex port of ``servers/visualizer/co2_vis.py``. Named for the same
``live_vis`` config value the Bokeh module answers to, so a station gains this
panel by adding a ``reflex:`` server and changing nothing else.
"""

__all__ = ["WS_PATH", "STATE_BASE", "Y_LABEL", "build", "panel_id"]

from helao.deploy.hte.servers.reflex._live import make_live_panel, suffix_matcher

WS_PATH = "ws_live"
Y_LABEL = "CO2 (ppm)"

#: The Bokeh panel plots a rolling mean of the raw ppm alongside it.
STATE_BASE, build, panel_id = make_live_panel(
    "co2", Y_LABEL, wants_mean=suffix_matcher("co2_ppm")
)
