"""Reflex panel for a Gamry potentiostat's per-action data.

Reflex port of ``servers/visualizer/gamry_vis.py``: the running action's trace
beside the previous action's, with selectable x and y columns defaulting to
the pair that suits the technique. Named for the same ``action_vis`` config
value the Bokeh module answers to, so a station needs no config change.
"""

__all__ = ["WS_PATH", "STATE_BASE", "COLUMNS", "AXIS_MAP", "build", "panel_id"]

from helao.deploy.hte.servers.reflex._pstat_panel import make_pstat_panel

WS_PATH = "ws_data"

#: Columns the Gamry server streams, and the order the selectors offer them.
COLUMNS = ["t_s", "Ewe_V", "I_A", "Zreal", "Zimag", "Zfreq", "Zphz"]

#: Default axes per technique. Gamry reports impedance as Zreal/Zimag.
AXIS_MAP = {
    "run_CA": ("t_s", "I_A"),
    "run_CP": ("t_s", "Ewe_V"),
    "run_CV": ("Ewe_V", "I_A"),
    "run_OCV": ("t_s", "Ewe_V"),
    "run_RCA": ("t_s", "I_A"),
    "run_LSV": ("Ewe_V", "I_A"),
    "run_PEIS": ("Zreal", "Zimag"),
    "run_GEIS": ("Zreal", "Zimag"),
}

STATE_BASE, build, panel_id = make_pstat_panel(
    "gamry", "Gamry", COLUMNS, AXIS_MAP, per_channel=False
)
