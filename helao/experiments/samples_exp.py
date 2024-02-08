__all__ = [
    "create_liquid_sample",
    "create_gas_sample",
    "create_assembly_sample",
    "sort_plate_sample_no_list",
    "generate_sample_no_list",
    "load_liquid_sample"
]


from typing import Optional, List, Tuple
from socket import gethostname

from helao.helpers.premodels import Experiment, ActionPlanMaker

# from helaocore.models.action_start_condition import ActionStartCondition
from helaocore.models.sample import (
    LiquidSample,
    GasSample,
    AssemblySample,
    SolidSample,
)
from helaocore.models.machine import MachineModel


EXPERIMENTS = __all__

PAL_server = MachineModel(
    server_name="PAL", machine_name=gethostname().lower()
).as_dict()


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
                        "source": apm.pars.source,
                        "volume_ml": apm.pars.volume_ml,
                        "chemical": apm.pars.chemical,
                        "partial_molarity": apm.pars.partial_molarity,
                        "ph": apm.pars.ph,
                        "supplier": apm.pars.supplier,
                        "lot_number": apm.pars.lot_number,
                        "electrolyte": apm.pars.electrolyte_name,
                        "prep_date": apm.pars.prep_date,
                        "comment": apm.pars.comment,
                    }
                )
            ],
        },
    )

    return apm.action_list  # returns complete action list to orch


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
                        "source": apm.pars.source,
                        "volume_ml": apm.pars.volume_ml,
                        "chemical": apm.pars.chemical,
                        "partial_molarity": apm.pars.partial_molarity,
                        "supplier": apm.pars.supplier,
                        "lot_number": apm.pars.lot_number,
                        "prep_date": apm.pars.prep_date,
                        "comment": apm.pars.comment,
                    }
                )
            ],
        },
    )

    return apm.action_list  # returns complete action list to orch


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
    if len(apm.pars.solid_plate_ids) != len(apm.pars.solid_sample_nos):
        print(
            f"!!! ERROR: len(solid_plate_ids) != len(solid_sample_nos): "
            f"{len(apm.pars.solid_plate_ids)} != {len(apm.pars.solid_sample_nos)}"
        )
        return apm.action_list

    liquid_list = [
        LiquidSample(machine_name=gethostname().lower(), sample_no=sample_no)
        for sample_no in apm.pars.liquid_sample_nos
    ]
    gas_list = [
        GasSample(machine_name=gethostname().lower(), sample_no=sample_no)
        for sample_no in apm.pars.gas_sample_nos
    ]
    solid_list = [
        SolidSample(machine_name="legacy", plate_id=plate_id, sample_no=sample_no)
        for plate_id, sample_no in zip(
            apm.pars.solid_plate_ids, apm.pars.solid_sample_nos
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
                        # "source": apm.pars.source,
                        "volume_ml": apm.pars.volume_ml,
                        # "chemical": apm.pars.chemical,
                        # "partial_molarity": apm.pars.partial_molarity,
                        # "supplier": apm.pars.supplier,
                        # "lot_number": apm.pars.lot_number,
                        "comment": apm.pars.comment,
                    }
                )
            ],
        },
    )

    return apm.action_list  # returns complete action list to orch


def sort_plate_sample_no_list(
    experiment: Experiment,
    experiment_version: int = 1,
    plate_sample_no_list: list = [2],
):
    """tbd"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    return apm.action_list  # returns complete action list to orch


def generate_sample_no_list(
    experiment: Experiment,
    experiment_version: int = 1,
    plate_id: int = 1,
    sample_code: int = 0,
    skip_n_samples: int = 0,
    direction: str = None,
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
            "plate_id": apm.pars.plate_id,
            "sample_code": apm.pars.sample_code,
            "skip_n_samples": apm.pars.skip_n_samples,
            # "direction":apm.pars.direction,
            # "sample_nos":apm.pars.sample_nos,
            # "sample_nos_operator":apm.pars.sample_nos_operator,
            # "platemap_xys":apm.pars.platemap_xys,
            # "platemap_xys_operator":apm.pars.platemap_xys_operator,
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
        sample_no=apm.pars.liquid_sample_no, machine_name=apm.pars.machine_name
    )

    apm.add(
        PAL_server,
        "archive_tray_load",
        {
            "load_sample_in": liquid,
            "tray": apm.pars.tray,
            "slot": apm.pars.slot,
            "vial": apm.pars.vial
        },
    )

    return apm.action_list  # returns complete action list to orch
