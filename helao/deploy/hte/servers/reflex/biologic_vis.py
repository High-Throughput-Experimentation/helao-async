"""Reflex panel for a BioLogic potentiostat's per-action data.

Reflex port of ``servers/visualizer/biologic_vis.py``: one plot pair per
hardware channel -- the running action beside the previous one -- with
selectable x and y columns defaulting to the pair that suits the technique.
Channels are discovered from the ``channel`` column the packets carry, so a
station with any number of them is handled without configuration.
"""

__all__ = ["WS_PATH", "STATE_BASE", "COLUMNS", "AXIS_MAP", "build", "panel_id"]

from helao.deploy.hte.servers.reflex._pstat_panel import make_pstat_panel

WS_PATH = "ws_data"

#: Columns the BioLogic server streams. It reports impedance as R_ohm/X_ohm
#: rather than Gamry's Zreal/Zimag.
COLUMNS = ["t_s", "Ewe_V", "I_A", "P_W", "R_ohm", "X_ohm"]

#: Default axes per technique.
AXIS_MAP = {
    "run_CA": ("t_s", "I_A"),
    "run_CP": ("t_s", "Ewe_V"),
    "run_CV": ("Ewe_V", "I_A"),
    "run_OCV": ("t_s", "Ewe_V"),
    "run_PEIS": ("R_ohm", "X_ohm"),
    "run_CAOCV": ("t_s", "I_A"),
}

STATE_BASE, build, panel_id = make_pstat_panel(
    "biologic", "BioLogic", COLUMNS, AXIS_MAP, per_channel=True
)
