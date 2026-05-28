__all__ = [
    "XRFS_postseq",
]

from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


def XRFS_postseq(
    sequence_version: int = 1,
    sequence_zip_path: str = "",
    params: dict = {},
) -> list:
    """Build a post-sequence that runs the XRFS standards calibration.

    Args:
        sequence_version: Version tag for the sequence definition.
        sequence_zip_path: Path to the zipped sequence archive to analyze.
        params: Extra parameters forwarded to the calibration experiment.

    Returns:
        list: Ordered list of planned ``Experiment`` objects.
    """
    epm = ExperimentPlanMaker()
    epm.add(
        "XRFS_standards_calibration",
        {
            "sequence_zip_path": sequence_zip_path,
            "params": params
        },
    )

    return epm.planned_experiments  # returns complete experiment list
