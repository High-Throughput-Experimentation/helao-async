"""Sequence library exposing a single looping chronopotentiometry program."""

__all__ = [
    "CP_loop",
]


from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


def CP_loop(
    sequence_version: int = 1,
    CP_current: float = 0.001,
    CP_duration_sec: float = 3600,
    CP_samplerate_sec: float = 0.1,
    gamry_i_range: str = "auto",
    comment: str = "",
    num_repeats: int = 1,
    alert_duration_sec: float = -1,
    alert_above: bool = True,
    alert_sleep_sec: float = -1,
    alert_thresh_Ewe_V: float = -1,
    stop_voltage_min: str = "",
    stop_voltage_max: str = "",
    stop_voltage_min_delay_pts: str = "",
    stop_voltage_max_delay_pts: str = "",
) -> list:
    """Build a sequence that runs a single ``PSTAT_exp_CP`` experiment.

    The added experiment internally loops chronopotentiometry for
    ``num_repeats`` iterations and forwards all alert and stop-voltage
    parameters to the underlying potentiostat action.

    Args:
        sequence_version: Version tag for the sequence definition.
        CP_current: CP current setpoint in amps.
        CP_duration_sec: Duration of one CP loop iteration in seconds.
        CP_samplerate_sec: Data acquisition interval in seconds.
        gamry_i_range: Gamry current range string (e.g. ``"auto"``).
        comment: User comment forwarded to the experiment.
        num_repeats: Number of CP loop iterations to perform.
        alert_duration_sec: Duration over which the alert threshold is
            evaluated; negative disables.
        alert_above: If True, alert when voltage stays above threshold,
            else when below.
        alert_sleep_sec: Sleep between alert checks in seconds.
        alert_thresh_Ewe_V: Voltage threshold used to trigger an alert.
        stop_voltage_min: Lower voltage stop limit (string-encoded).
        stop_voltage_max: Upper voltage stop limit (string-encoded).
        stop_voltage_min_delay_pts: Consecutive points below the min limit
            required to stop.
        stop_voltage_max_delay_pts: Consecutive points above the max limit
            required to stop.

    Returns:
        list: Ordered list of planned ``Experiment`` objects.
    """

    epm = ExperimentPlanMaker()

    # CP
    epm.add(
        "PSTAT_exp_CP",
        {
            "current": CP_current,
            "acqinterval_s": CP_samplerate_sec,
            "duration_s": CP_duration_sec,
            "gamry_i_range": gamry_i_range,
            "comment": comment,
            "num_repeats": num_repeats,
            "alert_duration_sec": alert_duration_sec,
            "alert_above": alert_above,
            "alert_sleep_sec": alert_sleep_sec,
            "alert_thresh_Ewe_V": alert_thresh_Ewe_V,
            "stop_voltage_min": stop_voltage_min,
            "stop_voltage_max": stop_voltage_max,
            "stop_voltage_min_delay_pts": stop_voltage_min_delay_pts,
            "stop_voltage_max_delay_pts": stop_voltage_max_delay_pts,
        },
    )

    return epm.planned_experiments  # returns complete experiment list
