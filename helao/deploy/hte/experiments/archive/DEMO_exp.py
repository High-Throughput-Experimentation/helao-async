"""Archived demo experiment library wrapping basic PSTAT techniques."""

__all__ = [
    "DEMO_sub_CP",
    "DEMO_sub_CA",
    "DEMO_sub_OCV",
]

###
from socket import gethostname

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helao.core.models.machine import MachineModel
from helao.helpers.constants import REF_TABLE
from helao.helpers.lib_decorators import experiment

# list valid experiment functions
EXPERIMENTS = __all__

ORCH_HOST = gethostname().lower()
PSTAT_server = MachineModel(server_name="PSTAT", machine_name=ORCH_HOST).as_dict()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).as_dict()


@experiment(version=1)
def DEMO_sub_CP(
    experiment: Experiment,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CP_current: float = 0.0,
    SampleRate: float = 0.01,
    CP_duration_sec: float = 60,
    IErange: str = "auto",
) -> list:
    """Queue a PSTAT ``run_CP`` step with the supplied current and duration.

    Args:
        experiment: Parent experiment supplied by the orchestrator.
        WE_versus: Working-electrode reference frame label.
        ref_type: Reference electrode type label.
        pH: Solution pH (used for downstream RHE conversions).
        CP_current: Applied current in amps.
        SampleRate: Sample interval in seconds.
        CP_duration_sec: Step duration in seconds.
        IErange: Gamry current range string.

    Returns:
        List with a single PSTAT ``run_CP`` action.
    """

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


@experiment(version=1)
def DEMO_sub_CA(
    experiment: Experiment,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    ref_type: str = "leakless",
    pH: float = 6.8,
) -> list:
    """Queue a PSTAT ``run_CA`` step after converting the bias to vs. reference.

    Converts ``WE_potential__V`` from the supplied frame to vs. reference using
    ``REF_TABLE[ref_type]`` and the pH when ``WE_versus == 'rhe'``.

    Args:
        experiment: Parent experiment supplied by the orchestrator.
        WE_potential__V: Working-electrode bias in the chosen frame.
        WE_versus: Frame label: ``"ref"`` or ``"rhe"``.
        CA_duration_sec: Step duration in seconds.
        SampleRate: Sample interval in seconds.
        IErange: Gamry current range string.
        ref_offset__V: Reference-electrode offset (V).
        ref_type: Reference electrode type label (must be in ``REF_TABLE``).
        pH: Solution pH.

    Returns:
        List with a single PSTAT ``run_CA`` action.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    if WE_versus == "ref":
        potential_vsRef = WE_potential__V - 1.0 * ref_offset__V

    elif WE_versus == "rhe":
        potential_vsRef = (
            WE_potential__V - 1.0 * ref_offset__V - 0.059 * pH - REF_TABLE[ref_type]
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


@experiment(version=1)
def DEMO_sub_OCV(
    experiment: Experiment,
    Tval__s: float = 900.0,
    IErange: str = "auto",
) -> list:
    """Queue a PSTAT ``run_OCV`` step with the supplied duration.

    Args:
        experiment: Parent experiment supplied by the orchestrator.
        Tval__s: OCV duration in seconds.
        IErange: Gamry current range string.

    Returns:
        List with a single PSTAT ``run_OCV`` action.
    """
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
