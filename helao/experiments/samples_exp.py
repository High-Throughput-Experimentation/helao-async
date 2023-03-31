__all__ = [
    "create_liquid_sample",
    "create_gas_sample",
    "create_assembly_sample",
    "sort_plate_sample_no_list",
    "generate_sample_no_list",
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

PAL_server = MachineModel(server_name="PAL", machine_name=gethostname()).clean_dict()


def create_liquid_sample(
    experiment: Experiment,
    experiment_version: int = 1,
    volume_ml: Optional[float] = 1.0,
    source: Optional[List[str]] = ["source1", "source2"],
    partial_molarity: Optional[List[str]] = ["partial_molarity1", "partial_molarity2"],
    chemical: Optional[List[str]] = ["chemical1", "chemical2"],
    ph: Optional[float] = 7.0,
    supplier: Optional[List[str]] = ["supplier1", "supplier2"],
    lot_number: Optional[List[str]] = ["lot1", "lot2"],
    electrolyte_name: Optional [str] = "name",
    prep_date: Optional [str] = "2000-01-01",
    comment: Optional[str] = "comment",
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
                        "machine_name": gethostname(),
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
    volume_ml: Optional[float] = 1.0,
    source: Optional[List[str]] = ["source1", "source2"],
    partial_molarity: Optional[List[str]] = ["partial_molarity1", "partial_molarity2"],
    chemical: Optional[List[str]] = ["chemical1", "chemical2"],
    supplier: Optional[List[str]] = ["supplier1", "supplier2"],
    lot_number: Optional[List[str]] = ["lot1", "lot2"],
    prep_date: Optional [str] = "2000-01-01",
    comment: Optional[str] = "comment",
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
                        "machine_name": gethostname(),
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
    liquid_sample_nos: Optional[List[int]] = [1, 2],
    gas_sample_nos: Optional[List[int]] = [1, 2],
    solid_plate_ids: Optional[List[int]] = [1, 2],
    solid_sample_nos: Optional[List[int]] = [1, 2],
    volume_ml: Optional[float] = 1.0,
    # source: Optional[List[str]] = ["source1","source2"],
    # partial_molarity:  Optional[List[str]] = ["partial_molarity1","partial_molarity2"],
    # chemical: Optional[List[str]] = ["chemical1","chemical2"],
    # supplier: Optional[List[str]] = ["supplier1","supplier2"],
    # lot_number: Optional[List[str]] = ["lot1","lot2"],
    comment: Optional[str] = "comment",
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
        LiquidSample(machine_name=gethostname(), sample_no=sample_no)
        for sample_no in apm.pars.liquid_sample_nos
    ]
    gas_list = [
        GasSample(machine_name=gethostname(), sample_no=sample_no)
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
                        "machine_name": gethostname(),
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
    plate_id: Optional[int] = 1,
    sample_code: Optional[int] = 0,
    skip_n_samples: Optional[int] = 0,
    direction: Optional[str] = None,
    sample_nos: Optional[List[int]] = [],
    sample_nos_operator: Optional[str] = "",
    # platemap_xys: List[Tuple[int, int]] = [],
    platemap_xys: List[Tuple[int, int]] = [(None, None)],
    platemap_xys_operator: Optional[str] = "",
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

    return apm.action_list  # returns complete action list to orch
