from socket import gethostname

from helao.core.models.machine import MachineModel
from helao.helpers.premodels import Experiment, ActionPlanMaker

__all__ = ["PSTAT_exp_CP"]
EXPERIMENTS = __all__
PSTAT_server = MachineModel(server_name="PSTAT", machine_name=gethostname().lower()).as_dict()

def PSTAT_exp_CP(
    experiment: Experiment,
    experiment_version: int = 1,
    current: float = 0.0,
    duration_s: float = 60,
    acqinterval_s: float = 0.1,
    gamry_i_range: str = "auto",
    comment: str = "",
    num_repeats: int = 1,
):
    """Run a looping CP experiment for num_repeats times.

    Args:
        cp_current (float, optional): _description_. Defaults to 0.0.
        cp_duration_s (float, optional): _description_. Defaults to 60.
        acqinterval_s (float, optional): _description_. Defaults to 0.1.
        gamry_i_range (str, optional): _description_. Defaults to "auto".
        comment (str, optional): _description_. Defaults to "".
        num_repeats (int): number of loops. Defaults to 1.0

    Returns:
        list: a list of Action premodels
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    cp_params = {
        "Ival__A": current,
        "Tval__s": duration_s,
        "AcqInterval__s": acqinterval_s,
        "IErange": gamry_i_range,
        "comment": comment
    }

    for _ in range(num_repeats):
        apm.add(
            PSTAT_server,
            "run_CP",
            cp_params,
            technique_name="CP",
        )

    return apm.action_list  # returns complete action list to orch