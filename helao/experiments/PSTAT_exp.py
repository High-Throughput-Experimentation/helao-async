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
    alert_duration_sec: float = -1,
    alert_above: bool = True,
    alert_sleep_sec: float = -1,
    alert_thresh_Ewe_V: float = -1,
    stop_voltage_min: str = "",
    stop_voltage_max: str = "",
    stop_voltage_min_delay_pts: str = "",
    stop_voltage_max_delay_pts: str = "",
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
        "comment": comment,
        "alert_duration_s": alert_duration_sec,
        "alert_above": alert_above,
        "alert_sleep__s": alert_sleep_sec,
        "alertTreshEwe_V": alert_thresh_Ewe_V,
        "SetStopXMin": float(stop_voltage_min) if stop_voltage_min!="" else None,
        "SetStopXMax": float(stop_voltage_max) if stop_voltage_max!="" else None,
        "SetStopAtDelayXMin": int(stop_voltage_min_delay_pts) if stop_voltage_min_delay_pts!="" else None,
        "SetStopAtDelayXMax": int(stop_voltage_max_delay_pts) if stop_voltage_max_delay_pts!="" else None,
    }

    for _ in range(num_repeats):
        apm.add(
            PSTAT_server,
            "run_CP",
            cp_params,
            technique_name="CP",
        )

    return apm.planned_actions  # returns complete action list to orch