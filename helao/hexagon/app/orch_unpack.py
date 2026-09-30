"""Sequence-unpacking free functions + ``PLATE_API`` singleton extracted from
``Orch`` (CARDS P5, Stage S6).

``Orch.unpack_sequence``/``get_sequence_codehash``/``seq_unpacker``/
``verify_plate_in_params`` implement the orchestrator's sequence-unpacking
"cluster": expanding a named sequence-library entry into its planned
experiments, resolving a sequence's cached code hash, pushing planned
experiments from the active sequence onto the experiment deque, and
confirming a plate-id parameter resolves to a valid platemap. Unlike the
other P5 extractions, three of these four are near-pure/stateless enough to
become plain module-level functions (taking the state they need as explicit
params) rather than a stateful collaborator class; ``seq_unpacker`` alone
takes the live ``orch`` handle since it reads/writes several ``Orch``
attributes across an ``await``.

``HTEPlateAPI``/``PLATE_API`` also move here (their sole previous purpose was
backing ``verify_plate_in_params``): ``PLATE_API = HTEPlateAPI()`` is a
module-level singleton on this module, and this module attribute is the one
patch point for it. Native code reads ``orch_unpack.PLATE_API`` at call time
(B7a, D-B7a.2); ``helao/core/servers/orch_unpack.py`` and ``orch.py`` only
re-export it, so patching either of those names reaches nothing.

Per the P5 constraints (:doc:`CARDS_REFACTOR_P5.md` sec 3.1 rule 5 "no
behavior fixes ride along"): every body below is moved verbatim, with only
``self.<x>`` accesses turned into explicit params (``unpack_sequence``/
``get_sequence_codehash``) or ``orch.<x>`` (``seq_unpacker``).
``verify_plate_in_params`` needed no ``self`` rewrite at all -- it only ever
touched the module-level ``PLATE_API``/``LOGGER`` and its own ``paramd`` arg.

Moved here from ``helao/core/servers/orch_unpack.py`` by B7a, code
unchanged (``seq_unpacker`` carries the E-STOP ``still_active`` guard merged
from unstable); that module is now a re-export B7b deletes. This module imports
nothing from ``helao/core/servers/`` and must not start: the engine imports
it (through its re-export and ``orch.py``), never the other way round.
"""

from uuid import UUID

from helao.core.models.orchstatus import LoopStatus
from helao.helpers import helao_logging as logging
from helao.helpers.plate_api import HTEPlateAPI
from helao.helpers.premodels import Experiment

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


PLATE_API = HTEPlateAPI()


def unpack_sequence(
    sequence_name: str, sequence_params, sequence_lib
) -> list[Experiment]:
    """Invoke the named sequence factory and return the list of planned experiments.

    Args:
        sequence_name: Sequence library entry to expand.
        sequence_params: Keyword arguments forwarded to the sequence factory.
        sequence_lib: Mapping of sequence name to sequence factory callable.
    """
    if sequence_name in sequence_lib:
        return sequence_lib[sequence_name](**sequence_params)
    else:
        return []


def get_sequence_codehash(sequence_name: str, sequence_codehash_lib) -> UUID:
    """Return the cached code hash for the named sequence library entry."""
    return sequence_codehash_lib[sequence_name]


async def seq_unpacker(orch) -> None:
    """Push every planned experiment from the active sequence onto the experiment deque."""
    seq_uuid = orch.active_sequence.sequence_uuid
    planned = orch.active_sequence.planned_experiments

    def still_active() -> bool:
        """False once E-STOPped or once another sequence (or none) is active."""
        active = orch.active_sequence
        return (
            orch.globalstatusmodel.loop_state != LoopStatus.estopped
            and active is not None
            and active.sequence_uuid == seq_uuid
        )

    for i, experimentmodel in enumerate(planned):
        # An E-STOP can land at any await: ``estop_finish_active`` clears
        # ``experiment_dq`` and ``active_sequence``, and appending after that
        # would refill the queue with experiments that can never dispatch.
        # The guard runs before each append and again after it, because
        # ``add_experiment`` yields before it appends: an E-STOP landing inside
        # it must not be overwritten by ``started`` below. (The one experiment
        # that append may still drop into the queue is removed by
        # ``dispatch_experiment``'s no-active-sequence check.)
        if not still_active():
            LOGGER.warning(
                f"sequence {seq_uuid} is no longer active (estopped or replaced); "
                f"stopped unpacking at experiment {i} of {len(planned)}"
            )
            return
        # self.print_message(
        #     f"unpack experiment {experimentmodel.experiment_name}"
        # )
        if orch.seq_model.data_request_id is not None:
            experimentmodel.data_request_id = orch.seq_model.data_request_id
        await orch.add_experiment(seq=orch.seq_model, experimentmodel=experimentmodel)
        if not still_active():
            LOGGER.warning(
                f"sequence {seq_uuid} is no longer active (estopped or replaced); "
                f"stopped unpacking after experiment {i} of {len(planned)}"
            )
            return
        if i == 0:
            orch.globalstatusmodel.loop_state = LoopStatus.started


def verify_plate_in_params(paramd: dict) -> bool:
    """Confirm that any ``plate_id``/``solid_plate_id`` parameter resolves to a valid platemap.

    Args:
        paramd: Parameter dictionary to inspect.

    Returns:
        ``True`` if no plate parameter is present or a platemap was found.
    """
    plate_found = False
    if "solid_plate_id" in paramd or "plate_id" in paramd:
        # check for valid plate if solid_plate_id or plate_id is a sequence parameter
        if PLATE_API.has_access:
            for pid_key in ["solid_plate_id", "plate_id"]:
                pid_val = paramd.get(pid_key, None)
                if pid_val is not None:
                    platemap = PLATE_API.get_platemap_plateid(pid_val)
                    if platemap:
                        plate_found = True
                        LOGGER.info(
                            f"plate_id {pid_val} was found with a valid platemap"
                        )
                        break
        else:
            LOGGER.warning(
                "plate_id is a sequence parameter but there is no access to info and map file locations."
            )
    else:
        # no plate parameter, so act like it's fine
        plate_found = True
    return plate_found
