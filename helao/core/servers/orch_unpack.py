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
backing ``verify_plate_in_params``): ``PLATE_API = HTEPlateAPI()`` is now a
module-level singleton on this module, and ``orch.py`` re-imports it
(``from helao.core.servers.orch_unpack import PLATE_API``) so the existing
monkeypatch point (tests patching ``helao.core.servers.orch.PLATE_API``)
keeps working unchanged -- ``orch.py``'s name is just a second reference to
the same object this module owns.

Per the P5 constraints (:doc:`CARDS_REFACTOR_P5.md` sec 3.1 rule 5 "no
behavior fixes ride along"): every body below is moved verbatim, with only
``self.<x>`` accesses turned into explicit params (``unpack_sequence``/
``get_sequence_codehash``) or ``orch.<x>`` (``seq_unpacker``).
``verify_plate_in_params`` needed no ``self`` rewrite at all -- it only ever
touched the module-level ``PLATE_API``/``LOGGER`` and its own ``paramd`` arg.

CIRCULAR-IMPORT NOTE: ``orch.py`` imports this module at module top
(``from helao.core.servers import orch_unpack``), so this module must never
import from ``orch.py`` at module top. None of the functions below need
anything from ``orch.py``.
"""

from typing import List
from uuid import UUID

from helao.helpers import helao_logging as logging
from helao.helpers.plate_api import HTEPlateAPI
from helao.core.models.orchstatus import LoopStatus
from helao.helpers.premodels import Experiment

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


PLATE_API = HTEPlateAPI()


def unpack_sequence(
    sequence_name: str, sequence_params, sequence_lib
) -> List[Experiment]:
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
    for i, experimentmodel in enumerate(orch.active_sequence.planned_experiments):
        # self.print_message(
        #     f"unpack experiment {experimentmodel.experiment_name}"
        # )
        if orch.seq_model.data_request_id is not None:
            experimentmodel.data_request_id = orch.seq_model.data_request_id
        await orch.add_experiment(seq=orch.seq_model, experimentmodel=experimentmodel)
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
