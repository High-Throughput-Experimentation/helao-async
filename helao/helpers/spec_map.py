from socket import gethostname
from helao.core.models.machine import MachineModel as MM

SPEC_T_server = MM(server_name="SPEC_T", machine_name=gethostname().lower()).as_dict()
SPEC_R_server = MM(server_name="SPEC_R", machine_name=gethostname().lower()).as_dict()

SPEC_MAP = {"T_UVVIS": ["T"], "DR_UVVIS": ["R"], "TR_UVVIS": ["T", "R"]}

SPECSRV_MAP = {
    "T_UVVIS": [SPEC_T_server],
    "DR_UVVIS": [SPEC_R_server],
    "TR_UVVIS": [SPEC_T_server, SPEC_R_server],
}
