"""Experiment library exposing a looping chronopotentiometry run."""

from socket import gethostname

from helao.core.models.machine import MachineModel
from helao.helpers.lib_decorators import experiment
from helao.helpers.premodels import ActionPlanMaker

__all__ = ["PSTAT_exp_CP"]
EXPERIMENTS = __all__
PSTAT_server = MachineModel(
    server_name="PSTAT", machine_name=gethostname().lower()
).as_dict()


@experiment(version=1)
def PSTAT_exp_CP(
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
) -> list:
    """Queue ``num_repeats`` PSTAT ``run_CP`` actions sharing the same params.

    Builds a single CP parameter dict (including optional voltage stop limits)
    and appends one ``run_CP`` action per iteration of ``num_repeats``.

    Args:
        current: Applied current (A).
        duration_s: Duration of each CP step (s).
        acqinterval_s: Sample interval (s).
        gamry_i_range: Gamry current range string.
        comment: Free-form comment passed through to the driver.
        alert_duration_sec: Alert duration (s); ``-1`` disables.
        alert_above: True to alert when Ewe rises above the threshold.
        alert_sleep_sec: Sleep between alert checks (s); ``-1`` disables.
        alert_thresh_Ewe_V: Alert threshold Ewe (V).
        stop_voltage_min: Optional lower voltage stop (string; empty disables).
        stop_voltage_max: Optional upper voltage stop (string; empty disables).
        stop_voltage_min_delay_pts: Points the signal must dwell below
            ``stop_voltage_min`` before stopping (string; empty disables).
        stop_voltage_max_delay_pts: Points the signal must dwell above
            ``stop_voltage_max`` before stopping (string; empty disables).
        num_repeats: Number of times to queue the CP action.

    Returns:
        List of planned PSTAT ``run_CP`` actions.
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
        "SetStopXMin": float(stop_voltage_min) if stop_voltage_min != "" else None,
        "SetStopXMax": float(stop_voltage_max) if stop_voltage_max != "" else None,
        "SetStopAtDelayXMin": (
            int(stop_voltage_min_delay_pts)
            if stop_voltage_min_delay_pts != ""
            else None
        ),
        "SetStopAtDelayXMax": (
            int(stop_voltage_max_delay_pts)
            if stop_voltage_max_delay_pts != ""
            else None
        ),
    }

    for _ in range(num_repeats):
        apm.add(
            PSTAT_server,
            "run_CP",
            cp_params,
            technique_name="CP",
        )

    return apm.planned_actions  # returns complete action list to orch
