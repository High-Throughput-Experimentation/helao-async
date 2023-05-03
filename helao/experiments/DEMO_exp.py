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
from helaocore.models.machine import MachineModel
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

    if int(round(apm.pars.toggle_illum_time)) == -1:
        apm.pars.toggle_illum_time = apm.pars.CP_duration_sec

    apm.add(
        PSTAT_server,
        "run_CP",
        {
            "Ival": apm.pars.CP_current,
            "Tval__s": apm.pars.CP_duration_sec,
            "AcqInterval__s": apm.pars.SampleRate,
            "IErange": apm.pars.IErange,
        },
    )

    return apm.action_list  # returns complete action list to orch


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

    if apm.pars.WE_versus == "ref":
        potential_vsRef = apm.pars.WE_potential__V - 1.0 * apm.pars.ref_offset__V

    elif apm.pars.WE_versus == "rhe":
        potential_vsRef = (
            apm.pars.WE_potential__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[apm.pars.ref_type]
        )

    apm.add(
        PSTAT_server,
        "run_CA",
        {
            "Vval__V": potential_vsRef,
            "Tval__s": apm.pars.CA_duration_sec,
            "AcqInterval__s": apm.pars.SampleRate,
            "IErange": apm.pars.IErange,
        },
    )

    return apm.action_list


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
            "Tval__s": apm.pars.Tval__s,
            "SampleRate": 0.05,
            "IErange": apm.pars.IErange,
        },
    )

    return apm.action_list  # returns complete action list to orch
