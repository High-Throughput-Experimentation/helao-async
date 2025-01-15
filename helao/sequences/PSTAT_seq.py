"""
Sequence library for ECHE
"""

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
    comment: str = ""
    num_repeats: int = 1
):
    """Run a looping CP for num_repeats times.

    Args:
        CP_current (float, optional): CP current in amps. Defaults to 0.001.
        CP_duration_sec (float, optional): Duration of one CP loop iteration in seconds. Defaults to 3600.
        CP_samplerate_sec (float, optional): Data acquisition rate in seconds. Defaults to 0.1.
        gamry_i_range (str, optional): _description_. Defaults to "auto".
        comment (str, optional): User comment e.g. sample number. Defaults to "".
        num_repeats (int): Number of loop iterations. Defaults to 1

    Returns:
        list: a list of Action premodels
    """

    epm = ExperimentPlanMaker()


    # CP
    epm.add_experiment(
        "PSTAT_exp_CP_loop",
        {
            "CP_current": CP_current,
            "samplerate_sec": CP_samplerate_sec,
            "CP_duration_sec": CP_duration_sec,
            "gamry_i_range": gamry_i_range,
            "comment": comment
            "num_repeats": num_repeats
        },
    )


    return epm.experiment_plan_list  # returns complete experiment list


