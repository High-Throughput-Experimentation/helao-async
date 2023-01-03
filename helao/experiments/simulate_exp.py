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


"""
Action library for simulator

server_key must be a FastAPI action server defined in config
"""

__all__ = ["SIM_measure_CP"]

from socket import gethostname
from typing import Optional, List

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helaocore.models.machine import MachineModel


# list valid experiment functions
EXPERIMENTS = __all__

ORCH_HOST = gethostname()
ANA_server = MachineModel(server_name="ANA", machine_name=ORCH_HOST).json_dict()
PSTAT_server = MachineModel(server_name="PSTAT", machine_name=ORCH_HOST).json_dict()
MOTOR_server = MachineModel(server_name="MOTOR", machine_name=ORCH_HOST).json_dict()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).json_dict()
PAL_server = MachineModel(server_name="PAL", machine_name=ORCH_HOST).json_dict()


# given solution pH, element space, and element fractions, measure CP at 3 and 10 mA/cm2
def SIM_measure_CP(
    experiment: Experiment,
    experiment_version: int = 1,
    solution_ph: Optional[int] = 13,
    elements: Optional[List[str]] = [],
    element_fracs: Optional[List[float]] = [],
):
    apm = ActionPlanMaker()

    # find plate matching element, pH space
    apm.add(
        PAL_server,
        "query_plate",
        {"elements": apm.pars.elements, "ph": apm.pars.solution_ph},
        to_globalexp_params=["_plate_id"],
    )
    # load plate
    apm.add(
        PAL_server,
        "load_space",
        {},
        from_globalexp_params={"_plate_id": "plate_id"},
        to_globalexp_params=["_ph", "_elements"],
    )
    # find sample matching element fracs
    apm.add(
        PAL_server,
        "acquire",
        {"element_fracs": apm.pars.element_fracs},
        to_globalexp_params=["_acq_sample_no"],
    )
    # find plate x,y coordinates from sample_no
    apm.add(
        MOTOR_server,
        "solid_get_samples_xy",
        {},
        from_globalexp_params={"_plate_id": "plate_id", "_acq_sample_no": "sample_no"},
        to_globalexp_params=["_platexy"],
    )
    # move stage motors to sample x,y
    apm.add(MOTOR_server, "move", {}, from_globalexp_params={"_platexy": "d_mm"})
    # measure CP at 3mA/cm2 for 15 seconds
    apm.add(PSTAT_server, "run_CP", {"Ival": 3e-5, "Tval__s": 15.0})
    # calculate CP fom
    apm.add(
        ANA_server,
        "calc_cpfom",
        {"ph": apm.pars.solution_ph, "jmacm2": 3},
        from_globalexp_params={"_plate_id": "plate_id", "_acq_sample_no": "sample_no"},
    )
    # measure CP at 10mA/cm2 for 15 seconds
    apm.add(PSTAT_server, "run_CP", {"Ival": 1e-4, "Tval__s": 15.0})
    # calculate CP fom
    apm.add(
        ANA_server,
        "calc_cpfom",
        {"ph": apm.pars.solution_ph, "jmacm2": 10},
        from_globalexp_params={"_plate_id": "plate_id", "_acq_sample_no": "sample_no"},
    )

    return apm.action_list
