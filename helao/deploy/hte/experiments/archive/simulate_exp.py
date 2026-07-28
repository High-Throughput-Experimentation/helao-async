# 0.
# retrieve available spaces
# retrieve measured space and FOMs

# 1. setup screening, given pH and comp space
# load plate

# 2. measure CP 3mA and 10mA
# select sample
# move to sample
# measure sample
# measure sample
# extract FOMs


"""Archived simulator experiment library for screening-style demo workflows."""

__all__ = ["SIM_measure_CP"]

from socket import gethostname
from typing import List

from helao.helpers.premodels import ActionPlanMaker
from helao.core.models.machine import MachineModel
from helao.helpers.lib_decorators import experiment

# list valid experiment functions
EXPERIMENTS = __all__

ORCH_HOST = gethostname().lower()
ANA_server = MachineModel(server_name="ANA", machine_name=ORCH_HOST).as_dict()
PSTAT_server = MachineModel(server_name="PSTAT", machine_name=ORCH_HOST).as_dict()
MOTOR_server = MachineModel(server_name="MOTOR", machine_name=ORCH_HOST).as_dict()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).as_dict()
PAL_server = MachineModel(server_name="PAL", machine_name=ORCH_HOST).as_dict()


# given solution pH, element space, and element fractions, measure CP at 3 and 10 mA/cm2
@experiment(version=1)
def SIM_measure_CP(
    solution_ph: int = 13,
    elements: List[str] = [],
    element_fracs: List[float] = [],
) -> list:
    """Simulate sample selection and CP measurement at 3 and 10 mA/cm^2.

    Builds an action plan that queries PAL for a matching plate, loads the
    composition space, picks the sample closest to ``element_fracs``,
    resolves the plate XY, moves the MOTOR stage there, then runs two
    PSTAT ``run_CP`` steps with intervening CALC ``calc_cpfom`` calls.

    Args:
        solution_ph: Target pH used in PAL ``query_plate`` and CP FOM calls.
        elements: Element-space identifiers used when querying plates.
        element_fracs: Target composition fractions for the sample acquire.

    Returns:
        List of planned PAL/MOTOR/PSTAT/ANA actions for the simulated screen.
    """
    apm = ActionPlanMaker()

    # find plate matching element, pH space
    apm.add(
        PAL_server,
        "query_plate",
        {"elements": elements, "ph": solution_ph},
        to_global_params=["_plate_id"],
    )
    # load plate
    apm.add(
        PAL_server,
        "load_space",
        {},
        from_global_act_params={"_plate_id": "plate_id"},
        to_global_params=["_ph", "_elements"],
    )
    # find sample matching element fracs
    apm.add(
        PAL_server,
        "acquire",
        {"element_fracs": element_fracs},
        to_global_params=["_acq_sample_no"],
    )
    # find plate x,y coordinates from sample_no
    apm.add(
        MOTOR_server,
        "solid_get_samples_xy",
        {},
        from_global_act_params={"_plate_id": "plate_id", "_acq_sample_no": "sample_no"},
        to_global_params=["_platexy"],
    )
    # move stage motors to sample x,y
    apm.add(MOTOR_server, "move", {}, from_global_act_params={"_platexy": "d_mm"})
    # measure CP at 3mA/cm2 for 15 seconds
    apm.add(PSTAT_server, "run_CP", {"Ival": 3e-5, "Tval__s": 15.0})
    # calculate CP fom
    apm.add(
        ANA_server,
        "calc_cpfom",
        {"ph": solution_ph, "jmacm2": 3},
        from_global_act_params={"_plate_id": "plate_id", "_acq_sample_no": "sample_no"},
    )
    # measure CP at 10mA/cm2 for 15 seconds
    apm.add(PSTAT_server, "run_CP", {"Ival": 1e-4, "Tval__s": 15.0})
    # calculate CP fom
    apm.add(
        ANA_server,
        "calc_cpfom",
        {"ph": solution_ph, "jmacm2": 10},
        from_global_act_params={"_plate_id": "plate_id", "_acq_sample_no": "sample_no"},
    )

    return apm.planned_actions
