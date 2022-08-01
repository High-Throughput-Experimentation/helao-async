"""
Sequence library for ECHE
"""

__all__ = [
    "UVIS_spectrometer",
    "UVIS_movetosample",
    "UVIS_move",
]


from helao.helpers.premodels import ExperimentPlanMaker
from helaocore.models.electrolyte import Electrolyte


SEQUENCES = __all__


def UVIS_movetosample(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no: int = 1,
):

    pl = ExperimentPlanMaker()

    pl.add_experiment(
        "UVIS_slave_movetosample",
        {
            #            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no,
        },
    )

    pl.add_experiment("UVIS_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list


def UVIS_move(
    sequence_version: int = 1,
    move_x_mm: float = 1.0,
    move_y_mm: float = 1.0,
):

    pl = ExperimentPlanMaker()

    pl.add_experiment(
        "UVIS_slave_move",
        {
            "x_mm": move_x_mm,
            "y_mm": move_y_mm,
        },
    )

    pl.add_experiment("UVIS_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list

def UVIS_spectrometer(
    sequence_version: int = 2,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    toggle_illum_time: float = -1,
    Spec_n_avg: int = 1,
    Spec_integration_time_ms: int = 35,
):

    pl = ExperimentPlanMaker()

    # (1) house keeping
    pl.add_experiment("UVIS_slave_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        pl.add_experiment(
            "UVIS_slave_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
            },
        )
        # 
        pl.add_experiment(
            "UVIS_slave_spectrometer_T",
            {
                "toggle_illum_time": toggle_illum_time,
                "spec_n_avg": Spec_n_avg,
                "spec_int_time": Spec_integration_time_ms,
            },
        )
        pl.add_experiment(
            "UVIS_slave_spectrometer_R",
            {
                "toggle_illum_time": toggle_illum_time,
                "spec_n_avg": Spec_n_avg,
                "spec_int_time": Spec_integration_time_ms,
            },
        )

        pl.add_experiment("UVIS_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list

