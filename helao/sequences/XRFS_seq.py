__all__ = [
    "XRFS_postseq",
]

import random
from typing import List
from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


def XRFS_postseq(
    sequence_version: int = 1,
    sequence_zip_path: str = "",
):
    epm = ExperimentPlanMaker()
    epm.add_experiment(
        "XRFS_standards_calibration",
        {
            "sequence_zip_path": sequence_zip_path,
        },
    )

    return epm.experiment_plan_list  # returns complete experiment list

