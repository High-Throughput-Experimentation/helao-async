"""Small constants and reference tables used across helao.

Consolidates the former ref_electrode, reference, and spec_map modules.
"""

__all__ = [
    "REF_TABLE",
    "Reference",
    "SPEC_MAP",
    "SPECSRV_MAP",
    "SPEC_T_server",
    "SPEC_R_server",
]

from socket import gethostname

from helao.framework.models.machine import MachineModel as MM


REF_TABLE = {"leakless": 0.21, "inhouse": 0.21, "rhe": 0.0}


class Reference:
    """Lightweight container describing a reference electrode.

    Attributes:
        name: Reference electrode identifier matching a key in :data:`REF_TABLE`.
        Vnhe: Offset from the normal hydrogen electrode in volts.
    """

    name: str
    Vnhe: float


SPEC_T_server = MM(server_name="SPEC_T", machine_name=gethostname().lower()).as_dict()
SPEC_R_server = MM(server_name="SPEC_R", machine_name=gethostname().lower()).as_dict()

SPEC_MAP = {"T_UVVIS": ["T"], "DR_UVVIS": ["R"], "TR_UVVIS": ["T", "R"]}

SPECSRV_MAP = {
    "T_UVVIS": [SPEC_T_server],
    "DR_UVVIS": [SPEC_R_server],
    "TR_UVVIS": [SPEC_T_server, SPEC_R_server],
}
