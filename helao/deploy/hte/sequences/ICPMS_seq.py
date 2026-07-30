SEQUENCES = [
    "ICPMS_postseq",
]

from helao.helpers.lib_decorators import sequence
from helao.helpers.premodels import ExperimentPlanMaker


@sequence(version=1)
def ICPMS_postseq(
    sequence_zip_path: str = "",
) -> list:
    """Build a post-sequence that runs the ICPMS concentration analysis.

    Args:
        sequence_zip_path: Path to the zipped sequence archive to analyze.

    Returns:
        list: Ordered list of planned ``Experiment`` objects.
    """
    epm = ExperimentPlanMaker()
    epm.add(
        "ICPMS_analysis_concentration",
        {
            "sequence_zip_path": sequence_zip_path,
        },
    )

    return epm.planned_experiments  # returns complete experiment list
