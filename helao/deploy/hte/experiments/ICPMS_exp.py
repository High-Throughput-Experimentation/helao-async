"""Experiment library wrapping ICP-MS concentration analysis."""

EXPERIMENTS = [
    "ICPMS_analysis_concentration",
]

from socket import gethostname

from helao.core.models.machine import MachineModel as MM
from helao.helpers.lib_decorators import experiment
from helao.helpers.premodels import ActionPlanMaker

ANA_server = MM(server_name="ANA", machine_name=gethostname().lower()).as_dict()


@experiment(version=1)
def ICPMS_analysis_concentration(
    sequence_path: str = "",
    params: dict = {},
) -> list:
    """Run the ANA server's local ICP-MS concentration analysis.

    Args:
        sequence_path: Path to a synced sequence directory on disk.
        params: Free-form parameter dict forwarded to the analyzer.

    Returns:
        List with a single ANA ``analyze_icpms_local`` action.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        ANA_server,
        "analyze_icpms_local",
        {
            "sequence_path": sequence_path,
            "params": params,
        },
    )
    return apm.planned_actions
