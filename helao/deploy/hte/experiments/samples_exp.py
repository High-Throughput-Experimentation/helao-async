"""Sample bookkeeping experiments: create/load PAL samples and orch waits."""

__all__ = [
    "create_liquid_sample",
    "create_gas_sample",
    "create_assembly_sample",
    "sort_plate_sample_no_list",
    "generate_sample_no_list",
    "load_liquid_sample",
    "create_and_load_liquid_sample",
    "orch_sub_wait",
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
) -> list:
    """Register a new custom liquid sample in the PAL sample database.

    Args:
        experiment: Parent experiment supplied by the orchestrator.
        experiment_version: Sub-experiment version tag.
        volume_ml: Sample volume in millilitres.
        source: List of source labels for the constituents.
        partial_molarity: Per-constituent partial molarity strings.
        chemical: Per-constituent chemical identifier strings.
        ph: Solution pH.
        supplier: Per-constituent supplier strings.
        lot_number: Per-constituent lot-number strings.
        electrolyte_name: Electrolyte name recorded with the sample.
        prep_date: Preparation date (ISO date string).
        comment: Free-form comment.

    Returns:
        List with a single PAL ``db_new_samples`` action creating the entry.
    """
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
) -> list:
    """Register a new custom gas sample in the PAL sample database.

    Args:
        experiment: Parent experiment supplied by the orchestrator.
        experiment_version: Sub-experiment version tag.
        volume_ml: Sample volume in millilitres.
        source: Source labels for the gas constituents.
        partial_molarity: Per-constituent partial molarity strings.
        chemical: Per-constituent chemical identifier strings.
        supplier: Per-constituent supplier strings.
        lot_number: Per-constituent lot-number strings.
        prep_date: Preparation date (ISO date string).
        comment: Free-form comment.

    Returns:
        List with a single PAL ``db_new_samples`` action creating the entry.
    """
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
) -> list:
    """Build a PAL assembly sample from existing liquid/gas/solid sample numbers.

    Looks up each constituent in the local PAL database, combines them into
    one ``AssemblySample`` payload, and registers the assembly via PAL
    ``db_new_samples``. Returns early with an empty list when the
    ``solid_plate_ids`` and ``solid_sample_nos`` lengths disagree.

    Args:
        experiment: Parent experiment supplied by the orchestrator.
        experiment_version: Sub-experiment version tag.
        liquid_sample_nos: Liquid sample numbers from the local liquid db.
        gas_sample_nos: Gas sample numbers from the local gas db.
        solid_plate_ids: Plate ids paired with ``solid_sample_nos``.
        solid_sample_nos: Sample numbers on the matching plates.
        volume_ml: Assembly volume in millilitres.
        comment: Free-form comment.

    Returns:
        List with a single PAL ``db_new_samples`` action, or an empty plan when
        the solid id/sample-no lists are mismatched.
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
        for plate_id, sample_no in zip(solid_plate_ids, solid_sample_nos)
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
) -> list:
    """Placeholder that returns an empty plan; reserved for plate-sample sorting.

    Args:
        experiment: Parent experiment supplied by the orchestrator.
        experiment_version: Sub-experiment version tag.
        plate_sample_no_list: Plate sample numbers (currently unused).

    Returns:
        Empty list of planned actions.
    """

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
    """Queue a PAL ``generate_plate_sample_no_list`` action for a plate.

    Note:
        This function currently does not return ``apm.planned_actions``.

    Args:
        experiment: Parent experiment supplied by the orchestrator.
        experiment_version: Sub-experiment version tag.
        plate_id: Plate id to enumerate.
        sample_code: Sample code filter passed to PAL.
        skip_n_samples: Number of samples to skip in the resulting list.
        direction: Optional traversal direction hint (unused; PAL-side).
        sample_nos: Optional explicit sample-number filter (unused; PAL-side).
        sample_nos_operator: Combinator for ``sample_nos`` (unused).
        platemap_xys: Optional XY filter pairs (unused; PAL-side).
        platemap_xys_operator: Combinator for ``platemap_xys`` (unused).
    """

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
    vial: int = 0,
) -> list:
    """Load an existing liquid sample into a PAL tray/slot/vial position.

    Args:
        experiment: Parent experiment supplied by the orchestrator.
        experiment_version: Sub-experiment version tag.
        liquid_sample_no: Sample number to load.
        machine_name: Machine the sample is registered against.
        tray: PAL tray index.
        slot: PAL slot index within the tray.
        vial: PAL vial index within the slot.

    Returns:
        List with a single PAL ``archive_tray_load`` action.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    liquid = LiquidSample(sample_no=liquid_sample_no, machine_name=machine_name)

    apm.add(
        PAL_server,
        "archive_tray_load",
        {"load_sample_in": liquid, "tray": tray, "slot": slot, "vial": vial},
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
    vial: int = 0,
) -> list:
    """Create a new liquid sample and immediately load it into a PAL vial.

    Registers the sample via PAL ``db_new_samples``, captures the returned
    sample number, then runs PAL ``archive_tray_load`` to deposit it in the
    chosen tray/slot/vial.

    Args:
        experiment: Parent experiment supplied by the orchestrator.
        experiment_version: Sub-experiment version tag.
        volume_ml: Sample volume in millilitres.
        source: List of source labels.
        partial_molarity: Per-constituent partial molarity strings.
        chemical: Per-constituent chemical identifier strings.
        ph: Solution pH.
        supplier: Per-constituent supplier strings.
        lot_number: Per-constituent lot-number strings.
        electrolyte_name: Electrolyte label recorded on the sample.
        prep_date: Preparation date (ISO date string).
        comment: Free-form comment.
        tray: PAL tray index for loading.
        slot: PAL slot index within the tray.
        vial: PAL vial index within the slot.

    Returns:
        List of PAL ``db_new_samples`` and ``archive_tray_load`` actions.
    """
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
        to_global_params=["_fast_sample_out"],
    )

    apm.add(
        PAL_server,
        "archive_tray_load",
        {"tray": tray, "slot": slot, "vial": vial},
        from_global_act_params={"_fast_sample_out": "load_sample_in"},
    )

    return apm.planned_actions  # returns complete action list to orch


def orch_sub_wait(
    experiment: Experiment,
    experiment_version: int = 2,
    wait_time_s: float = 10,
) -> list:
    """Ask the orchestrator to pause for ``wait_time_s`` seconds.

    Args:
        experiment: Parent experiment supplied by the orchestrator.
        experiment_version: Sub-experiment version tag.
        wait_time_s: Wait duration in seconds.

    Returns:
        List with a single ORCH ``wait`` action.
    """
    apm = ActionPlanMaker()

    apm.add(ORCH_server, "wait", {"waittime": wait_time_s})
    return apm.planned_actions  # returns complete action list to orch
