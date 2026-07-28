"""Queue-persistence collaborator extracted from ``Orch`` (CARDS P5, Stage S2).

``Orch.export_queues``/``Orch.import_queues`` pickle (respectively restore) the
run deques, active/last sequence and experiment, the global status model, and
the action/experiment/sequence histories to/from ``STATES/queues.pck``. This
module moves that pickle mechanics into a ``QueuePersister`` collaborator that
``Orch`` delegates to.

Per the P5 constraints (:doc:`CARDS_REFACTOR_P5.md` sec 3.1 rule 3):
``import_queues`` *reassigns* ``globalstatusmodel``, ``active_*``, ``last_*``,
and the history deques, and ``loop_task_dispatch_experiment`` (``orch.py:933``)
separately reassigns ``action_dq``. ``QueuePersister`` therefore caches no
shared mutable state -- it holds only the ``orch`` back-reference and reads
every deque/attribute through it at call time, so a reassignment made between
construction and a call (or between two calls) is always observed. Behavior is
byte-identical to the original inline methods: same pickle payload dict (keys
and value types), same file path (``STATES/queues.pck``), same
timestamped-filename variant, and the same restored-file archival
(``queues_imported_<ts>.pck``).

Pickle safety: the payload dict pickled by :meth:`export_queues` contains only
plain model instances and list/dict data -- never a ``QueuePersister``
instance or any other collaborator -- so a ``queues.pck`` written before this
stage still imports cleanly after it, and vice versa.
"""

import pickle
import os
from datetime import datetime
from typing import Optional

from helao.helpers import helao_logging as logging
from helao.helpers.time_utils import gen_uuid
from helao.helpers.dequedict import DequeDict

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class QueuePersister:
    """Pickle export/import of an ``Orch``'s run queues and related state.

    Holds only the ``orch`` back-reference (never a cached deque/attribute),
    per the call-time state resolution rule -- see module docstring.
    """

    def __init__(self, orch):
        self.orch = orch

    def export_queues(self, timestamp_pck: bool = False) -> str:
        """Pickle the deques, active/last sequence and experiment, and histories under ``STATES/``.

        Args:
            timestamp_pck: When True, embed a timestamp in the pickle filename.

        Returns:
            Filesystem path of the written pickle file.
        """
        orch = self.orch
        save_dir = orch.world_cfg["root"]
        queue_dict = {
            "seq": list(orch.sequence_dq),
            "exp": list(orch.experiment_dq),
            "act": list(orch.action_dq),
            "active_exp": orch.active_experiment,
            "last_exp": orch.last_experiment,
            "active_seq": orch.active_sequence,
            "last_seq": orch.last_sequence,
            "active_counter": orch.active_seq_exp_counter,
            "last_act": orch.last_action_uuid,
            "last_dispatched_act": orch.last_dispatched_action_uuid,
            "globalstatusmodel": orch.globalstatusmodel,
            "action_history": list(orch.action_history.items()),
            "experiment_history": list(orch.experiment_history.items()),
            "sequence_history": list(orch.sequence_history.items()),
        }
        if orch.active_run_id is not None:
            queue_dict["active_run_id"] = orch.active_run_id
        if timestamp_pck:
            pck_name = f"queues_{datetime.now().strftime('%y%m%d.%H%M%S')}.pck"
        else:
            pck_name = "queues.pck"
        save_path = os.path.join(save_dir, "STATES", pck_name)
        pickle.dump(queue_dict, open(save_path, "wb"))
        return save_path

    def import_queues(self, pck_path: Optional[str] = None) -> str:
        """Restore deques/active/last state from a previously exported pickle.

        Args:
            pck_path: Optional explicit path to the pickle; defaults to
                ``<root>/STATES/queues.pck``.

        Returns:
            The path that was loaded (or attempted).
        """
        orch = self.orch
        save_dir = orch.world_cfg["root"]
        if pck_path is None:
            save_path = os.path.join(save_dir, "STATES", "queues.pck")
        else:
            save_path = pck_path.strip('"').strip("'")
        if os.path.exists(save_path):
            queue_dict = pickle.load(open(save_path, "rb"))
        else:
            LOGGER.info("Exported queues.pck does not exist. Cannot restore.")
            return save_path
        if orch.sequence_dq or orch.experiment_dq or orch.action_dq:
            LOGGER.info("Existing queues are not empty. Cannot restore.")
        else:
            try:
                LOGGER.info("Restoring queues from saved pck.")
                for x in queue_dict["act"]:
                    orch.action_dq.append(x)
                for x in queue_dict["exp"]:
                    orch.experiment_dq.append(x)
                for x in queue_dict["seq"]:
                    if len(orch.sequence_dq) == 0:
                        orch.active_run_id = gen_uuid()
                    orch.sequence_dq.append(x)
                orch.active_experiment = queue_dict["active_exp"]
                orch.last_experiment = queue_dict["last_exp"]
                orch.active_sequence = queue_dict["active_seq"]
                orch.last_sequence = queue_dict["last_seq"]
                orch.active_seq_exp_counter = queue_dict["active_counter"]
                orch.last_action_uuid = queue_dict["last_act"]
                orch.last_dispatched_action_uuid = queue_dict["last_dispatched_act"]
                orch.globalstatusmodel = queue_dict["globalstatusmodel"]
                orch.active_run_id = queue_dict.get("active_run_id", None)
                orch.action_history = DequeDict(
                    queue_dict.get("action_history", []), maxlen=1000
                )
                orch.experiment_history = DequeDict(
                    queue_dict.get("experiment_history", []), maxlen=1000
                )
                orch.sequence_history = DequeDict(
                    queue_dict.get("sequence_history", []), maxlen=1000
                )
                if pck_path is None:
                    # Consume the default queues.pck after a successful restore so
                    # a stale file cannot be auto-replayed on a later restart
                    # (e.g. hot-reload of an idle-empty orchestrator, which passes
                    # --restore unconditionally). Archive rather than delete so it
                    # stays recoverable. An explicitly-pathed restore is left
                    # untouched (the caller chose it deliberately).
                    try:
                        archived = save_path.replace(
                            ".pck",
                            f"_imported_{datetime.now().strftime('%y%m%d.%H%M%S')}.pck",
                        )
                        os.replace(save_path, archived)
                        LOGGER.info(f"Archived restored queue pck to {archived}.")
                    except OSError:
                        LOGGER.warning(
                            "Could not archive restored queue pck.", exc_info=True
                        )
            except Exception:
                LOGGER.warning(
                    "Error restoring queues from pck. Check if pck is compatible.",
                    exc_info=True,
                )
        return save_path
