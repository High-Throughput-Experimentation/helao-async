"""
Action library for DEMO

server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "DEMO_sub_CP",
    "DEMO_sub_CA",
    "DEMO_sub_OCV",
]

###
from socket import gethostname

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helao.core.models.machine import MachineModel
from helao.helpers.ref_electrode import REF_TABLE

# list valid experiment functions
EXPERIMENTS = __all__

ORCH_HOST = gethostname().lower()
PSTAT_server = MachineModel(server_name="PSTAT", machine_name=ORCH_HOST).as_dict()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).as_dict()


def DEMO_sub_CP(
    experiment: Experiment,
    experiment_version: int = 1,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CP_current: float = 0.0,
    SampleRate: float = 0.01,
    CP_duration_sec: float = 60,
    IErange: str = "auto",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    if int(round(toggle_illum_time)) == -1:
        toggle_illum_time = CP_duration_sec

    apm.add(
        PSTAT_server,
        "run_CP",
        {
            "Ival": CP_current,
            "Tval__s": CP_duration_sec,
            "AcqInterval__s": SampleRate,
            "IErange": IErange,
        },
    )

    return apm.planned_actions  # returns complete action list to orch


def DEMO_sub_CA(
    experiment: Experiment,
    experiment_version: int = 1,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    ref_type: str = "leakless",
    pH: float = 6.8,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    if WE_versus == "ref":
        potential_vsRef = WE_potential__V - 1.0 * ref_offset__V

    elif WE_versus == "rhe":
        potential_vsRef = (
            WE_potential__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )

    apm.add(
        PSTAT_server,
        "run_CA",
        {
            "Vval__V": potential_vsRef,
            "Tval__s": CA_duration_sec,
            "AcqInterval__s": SampleRate,
            "IErange": IErange,
        },
    )

    return apm.planned_actions


def DEMO_sub_OCV(
    experiment: Experiment,
    experiment_version: int = 1,
    Tval__s: float = 900.0,
    IErange: str = "auto",
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # OCV
    apm.add(
        PSTAT_server,
        "run_OCV",
        {
            "Tval__s": Tval__s,
            "SampleRate": 0.05,
            "IErange": IErange,
        },
    )

    return apm.planned_actions  # returns complete action list to orch
