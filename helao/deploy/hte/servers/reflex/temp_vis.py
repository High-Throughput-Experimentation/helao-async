"""Reflex panel for a temperature sensor's live datastream.

Reflex port of ``servers/visualizer/temp_vis.py``. The Bokeh panel plots the
configured ``dev_monitor`` channels with no rolling mean; the streamed columns
are taken as they arrive rather than re-derived from the config, so a channel
the driver publishes but the config omits is still visible.
"""

__all__ = ["WS_PATH", "STATE_BASE", "Y_LABEL", "build", "panel_id"]

from helao.deploy.hte.servers.reflex._live import make_live_panel

WS_PATH = "ws_live"
Y_LABEL = "Temperature (C)"

STATE_BASE, build, panel_id = make_live_panel("temp", Y_LABEL)
