__all__ = [
    "XRFS_postseq",
]

from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


def XRFS_postseq(
    sequence_version: int = 1,
    sequence_zip_path: str = "",
):
    epm = ExperimentPlanMaker()
    epm.add(
        "XRFS_standards_calibration",
        {
            "sequence_zip_path": sequence_zip_path,
        },
    )

    return epm.planned_experiments  # returns complete experiment list

