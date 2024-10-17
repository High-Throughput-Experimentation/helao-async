__all__ = [
    "ICPMS_analysis_concentration",
]

from socket import gethostname

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helaocore.models.machine import MachineModel as MM


EXPERIMENTS = __all__

ANA_server = MM(server_name="ANA", machine_name=gethostname().lower()).as_dict()


def ICPMS_analysis_concentration(
    experiment: Experiment,
    experiment_version: int = 1,
    sequence_zip_path: str = "",
    params: dict = {},
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        ANA_server,
        "analyze_icpms_local",
        {
            "sequence_zip_path": sequence_zip_path,
            "params": params,
        },
    )
    return apm.action_list
