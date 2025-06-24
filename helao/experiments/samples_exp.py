__all__ = [
    "create_liquid_sample",
    "create_gas_sample",
    "create_assembly_sample",
    "sort_plate_sample_no_list",
    "generate_sample_no_list",
    "load_liquid_sample",
    "create_and_load_liquid_sample",
    "orch_sub_wait"
]


from typing import Optional, List, Tuple
from socket import gethostname

from helao.helpers.premodels import Experiment, ActionPlanMaker

# from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.sample import (
    LiquidSample,
    GasSample,
    AssemblySample,
    SolidSample,
)
from helao.core.models.machine import MachineModel


EXPERIMENTS = __all__

PAL_server = MachineModel(
    server_name="PAL", machine_name=gethostname().lower()
).as_dict()

ORCH_HOST = gethostname()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).as_dict()

def create_liquid_sample(
    experiment: Experiment,
    experiment_version: int = 1,
    volume_ml: float = 1.0,
    source: List[str] = ["source1", "source2"],
    partial_molarity: List[str] = ["partial_molarity1", "partial_molarity2"],
    chemical: List[str] = ["chemical1", "chemical2"],
    ph: float = 7.0,
    supplier: List[str] = ["supplier1", "supplier2"],
    lot_number: List[str] = ["lot1", "lot2"],
    electrolyte_name: str = "name",
    prep_date: str = "2000-01-01",
    comment: str = "comment",
):
    """creates a custom liquid sample
    input fields contain json strings"""
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        PAL_server,
        "db_new_samples",
        {
            "fast_samples_in": [
                LiquidSample(
                    **{
                        "machine_name": gethostname().lower(),
                        "source": source,
                        "volume_ml": volume_ml,
                        "chemical": chemical,
                        "partial_molarity": partial_molarity,
                        "ph": ph,
                        "supplier": supplier,
                        "lot_number": lot_number,
                        "electrolyte": electrolyte_name,
                        "prep_date": prep_date,
                        "comment": comment,
                    }
                )
            ],
        },
    )

    return apm.planned_actions  # returns complete action list to orch


def create_gas_sample(
    experiment: Experiment,
    experiment_version: int = 1,
    volume_ml: float = 1.0,
    source: List[str] = ["source1", "source2"],
    partial_molarity: List[str] = ["partial_molarity1", "partial_molarity2"],
    chemical: List[str] = ["chemical1", "chemical2"],
    supplier: List[str] = ["supplier1", "supplier2"],
    lot_number: List[str] = ["lot1", "lot2"],
    prep_date: str = "2000-01-01",
    comment: str = "comment",
):
    """creates a custom gas sample
    input fields contain json strings"""
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        PAL_server,
        "db_new_samples",
        {
            "fast_samples_in": [
                GasSample(
                    **{
                        "machine_name": gethostname().lower(),
                        "source": source,
                        "volume_ml": volume_ml,
                        "chemical": chemical,
                        "partial_molarity": partial_molarity,
                        "supplier": supplier,
                        "lot_number": lot_number,
                        "prep_date": prep_date,
                        "comment": comment,
                    }
                )
            ],
        },
    )

    return apm.planned_actions  # returns complete action list to orch


def create_assembly_sample(
    experiment: Experiment,
    experiment_version: int = 1,
    liquid_sample_nos: List[int] = [1, 2],
    gas_sample_nos: List[int] = [1, 2],
    solid_plate_ids: List[int] = [1, 2],
    solid_sample_nos: List[int] = [1, 2],
    volume_ml: float = 1.0,
    # source: List[str] = ["source1","source2"],
    # partial_molarity:  List[str] = ["partial_molarity1","partial_molarity2"],
    # chemical: List[str] = ["chemical1","chemical2"],
    # supplier: List[str] = ["supplier1","supplier2"],
    # lot_number: List[str] = ["lot1","lot2"],
    comment: str = "comment",
):
    """creates a custom assembly sample
    from local samples
    input fields contain json strings
    Args:
        liquid_sample_nos: liquid sample numbers from local liquid sample db
        gas_sample_nos: liquid sample numbers from local gas sample db
        solid_plate_ids: plate ids
        solid_sample_nos: sample_no on plate (one plate_id for each sample_no)
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    # check first
    if len(solid_plate_ids) != len(solid_sample_nos):
        print(
            f"!!! ERROR: len(solid_plate_ids) != len(solid_sample_nos): "
            f"{len(solid_plate_ids)} != {len(solid_sample_nos)}"
        )
        return apm.planned_actions

    liquid_list = [
        LiquidSample(machine_name=gethostname().lower(), sample_no=sample_no)
        for sample_no in liquid_sample_nos
    ]
    gas_list = [
        GasSample(machine_name=gethostname().lower(), sample_no=sample_no)
        for sample_no in gas_sample_nos
    ]
    solid_list = [
        SolidSample(machine_name="legacy", plate_id=plate_id, sample_no=sample_no)
        for plate_id, sample_no in zip(
            solid_plate_ids, solid_sample_nos
        )
    ]

    # combine all samples now in a partlist
    parts = []
    for liquid in liquid_list:
        parts.append(liquid)
    for gas in gas_list:
        parts.append(gas)
    for solid in solid_list:
        parts.append(solid)

    apm.add(
        PAL_server,
        "db_new_samples",
        {
            "fast_samples_in": [
                AssemblySample(
                    **{
                        "machine_name": gethostname().lower(),
                        "parts": parts,
                        # "source": source,
                        "volume_ml": volume_ml,
                        # "chemical": chemical,
                        # "partial_molarity": partial_molarity,
                        # "supplier": supplier,
                        # "lot_number": lot_number,
                        "comment": comment,
                    }
                )
            ],
        },
    )

    return apm.planned_actions  # returns complete action list to orch


def sort_plate_sample_no_list(
    experiment: Experiment,
    experiment_version: int = 1,
    plate_sample_no_list: list = [2],
):
    """tbd"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    return apm.planned_actions  # returns complete action list to orch


def generate_sample_no_list(
    experiment: Experiment,
    experiment_version: int = 1,
    plate_id: int = 1,
    sample_code: int = 0,
    skip_n_samples: int = 0,
    direction: Optional[str] = None,
    sample_nos: List[int] = [],
    sample_nos_operator: str = "",
    # platemap_xys: List[Tuple[int, int]] = [],
    platemap_xys: List[Tuple[int, int]] = [(None, None)],
    platemap_xys_operator: str = "",
):
    """tbd"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        PAL_server,
        "generate_plate_sample_no_list",
        {
            "plate_id": plate_id,
            "sample_code": sample_code,
            "skip_n_samples": skip_n_samples,
            # "direction":direction,
            # "sample_nos":sample_nos,
            # "sample_nos_operator":sample_nos_operator,
            # "platemap_xys":platemap_xys,
            # "platemap_xys_operator":platemap_xys_operator,
        },
    )


def load_liquid_sample(
    experiment: Experiment,
    experiment_version: int = 1,
    liquid_sample_no: int = 0,
    machine_name: str = "hte-xxxx-xx",
    tray: int = 0,
    slot: int = 0,
    vial: int = 0
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    liquid = LiquidSample(
        sample_no=liquid_sample_no, machine_name=machine_name
    )

    apm.add(
        PAL_server,
        "archive_tray_load",
        {
            "load_sample_in": liquid,
            "tray": tray,
            "slot": slot,
            "vial": vial
        },
    )

    return apm.planned_actions  # returns complete action list to orch

def create_and_load_liquid_sample(
    experiment: Experiment,
    experiment_version: int = 1,
    volume_ml: float = 1.0,
    source: List[str] = ["source1", "source2"],
    partial_molarity: List[str] = ["partial_molarity1", "partial_molarity2"],
    chemical: List[str] = ["chemical1", "chemical2"],
    ph: float = 7.0,
    supplier: List[str] = ["supplier1", "supplier2"],
    lot_number: List[str] = ["lot1", "lot2"],
    electrolyte_name: str = "name",
    prep_date: str = "2000-01-01",
    comment: str = "comment",
    tray: int = 0,
    slot: int = 0,
    vial: int = 0
):
    """creates a custom liquid sample
    input fields contain json strings"""
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        PAL_server,
        "db_new_samples",
        {
            "fast_samples_in": [
                LiquidSample(
                    **{
                        "machine_name": gethostname().lower(),
                        "source": source,
                        "volume_ml": volume_ml,
                        "chemical": chemical,
                        "partial_molarity": partial_molarity,
                        "ph": ph,
                        "supplier": supplier,
                        "lot_number": lot_number,
                        "electrolyte": electrolyte_name,
                        "prep_date": prep_date,
                        "comment": comment,
                    }
                )
            ],
        },
        to_global_params=["_fast_sample_out"]
    )

    
    apm.add(
        PAL_server,
        "archive_tray_load",
        {
            "tray": tray,
            "slot": slot,
            "vial": vial
        },
        from_global_act_params={"_fast_sample_out": "load_sample_in"}
    )

    return apm.planned_actions  # returns complete action list to orch

def orch_sub_wait(
    experiment: Experiment,
    experiment_version: int = 2,
    wait_time_s: float = 10,
):
    apm = ActionPlanMaker()
       
    apm.add(ORCH_server, "wait", {"waittime": wait_time_s})
    return apm.planned_actions  # returns complete action list to orch