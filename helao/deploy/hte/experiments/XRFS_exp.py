"""Experiment library wrapping the XRFS standards-calibration analysis."""

__all__ = [
    "XRFS_standards_calibration",
]

from socket import gethostname

from helao.framework.domain.run_models import RunExperiment as Experiment
from helao.framework.domain.plan_makers import ActionPlanMaker
from helao.framework.models.machine import MachineModel as MM
from helao.framework.support.lib_decorators import experiment


EXPERIMENTS = __all__

ANA_server = MM(server_name="ANA", machine_name=gethostname().lower()).as_dict()


@experiment(version=1)
def XRFS_standards_calibration(
    sequence_zip_path: str = "",
    params: dict = {},
) -> list:
    """Run the ANA server's local XRFS standards calibration.

    Args:
        sequence_zip_path: Path to a zipped sequence archive on disk.
        params: Free-form parameter dict forwarded to the analyzer.

    Returns:
        List with a single ANA ``analyze_xrfs_local`` action.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        ANA_server,
        "analyze_xrfs_local",
        {
            "sequence_zip_path": sequence_zip_path,
            "params": params,
        },
    )
    return apm.planned_actions
