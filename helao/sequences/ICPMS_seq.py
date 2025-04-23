__all__ = [
    "ICPMS_postseq",
]

from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


def ICPMS_postseq(
    sequence_version: int = 1,
    sequence_zip_path: str = "",
):
    epm = ExperimentPlanMaker()
    epm.add_experiment(
        "ICPMS_analysis_concentration",
        {
            "sequence_zip_path": sequence_zip_path,
        },
    )

    return epm.experiment_plan_list  # returns complete experiment list

