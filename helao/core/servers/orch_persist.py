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
import re
from datetime import datetime
from typing import Optional

from helao.helpers import helao_logging as logging
from helao.helpers.time_utils import gen_uuid
from helao.helpers.dequedict import DequeDict

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

# Layout version of the ``queues.pck`` payload, compared on import so a pickle
# this code cannot faithfully restore is declined with a clear message instead of
# being half-applied.
#
# Bump ONLY when the pickled dict's keys or value types change incompatibly. This
# is deliberately NOT the release version: ``get_hlo_version()`` is the short git
# commit hash, so stamping that would reject every pickle after any unrelated
# commit -- which would break ``--restore`` and the hot-reload orchestrator
# restart that depends on it.
#
# Note this check only catches payloads whose *layout* changed. A payload that
# still matches but references a since-renamed model class fails earlier, when
# unpickling resolves the class; :meth:`QueuePersister.import_queues` quarantines
# that case separately.
QUEUE_PCK_SCHEMA = 1

# How many timestamped exports to keep. The dispatch post-loop writes one every
# time the orchestrator stops with non-empty queues, so uncapped they accumulate
# indefinitely -- instruments have been found holding files over a year old.
TIMESTAMPED_EXPORT_RETENTION = 5

# Matches only the timestamped export series written by ``export_queues``
# (``queues_<YYMMDD>.<HHMMSS>.pck``). Deliberately excludes the
# ``queues_imported_<ts>.pck`` and ``queues_unreadable_<ts>.pck`` archives: those
# are forensic records of a restore and of a failed load, and pruning them would
# delete the evidence someone is most likely to want.
_TIMESTAMPED_EXPORT_RE = re.compile(r"^queues_\d{6}\.\d{6}\.pck$")


class QueuePersister:
    """Pickle export/import of an ``Orch``'s run queues and related state.

    Holds only the ``orch`` back-reference (never a cached deque/attribute),
    per the call-time state resolution rule -- see module docstring.
    """

    def __init__(self, orch):
        self.orch = orch

    def export_queues(self, timestamp_pck: bool = False) -> str:
        """Pickle the deques, active/last sequence and experiment, and histories under ``STATES/``.

        Stamps :data:`QUEUE_PCK_SCHEMA` into the payload so :meth:`import_queues`
        can decline a layout it cannot restore. When ``timestamp_pck`` is set, the
        timestamped series is pruned to :data:`TIMESTAMPED_EXPORT_RETENTION` files
        afterwards.

        Args:
            timestamp_pck: When True, embed a timestamp in the pickle filename.

        Returns:
            Filesystem path of the written pickle file.
        """
        orch = self.orch
        save_dir = orch.world_cfg["root"]
        queue_dict = {
            "schema": QUEUE_PCK_SCHEMA,
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
        states_dir = os.path.join(save_dir, "STATES")
        save_path = os.path.join(states_dir, pck_name)
        with open(save_path, "wb") as f:
            pickle.dump(queue_dict, f)
        if timestamp_pck:
            self.prune_timestamped_exports(states_dir)
        return save_path

    def prune_timestamped_exports(
        self, states_dir: str, keep: int = TIMESTAMPED_EXPORT_RETENTION
    ) -> list:
        """Delete all but the newest ``keep`` timestamped exports in ``states_dir``.

        Only the ``queues_<YYMMDD>.<HHMMSS>.pck`` series is considered (see
        :data:`_TIMESTAMPED_EXPORT_RE`); the plain ``queues.pck`` and the
        ``_imported_``/``_unreadable_`` archives are left alone. Newest is decided
        by the timestamp in the filename rather than mtime, so a copied or touched
        file cannot reorder the series.

        Never raises: this runs from :meth:`export_queues`, which itself runs
        during orchestrator shutdown, and failing to tidy up must not turn into a
        failure to save the queues.

        Args:
            states_dir: The ``STATES`` directory to prune.
            keep: How many of the newest exports to retain.

        Returns:
            The filenames removed, newest-last.
        """
        try:
            names = sorted(
                n for n in os.listdir(states_dir) if _TIMESTAMPED_EXPORT_RE.match(n)
            )
        except Exception:
            LOGGER.error(
                f"Could not list '{states_dir}' to prune timestamped queue "
                f"exports; leaving them in place.",
                exc_info=True,
            )
            return []
        if len(names) <= keep:
            return []
        removed = []
        for name in names[:-keep]:
            try:
                os.remove(os.path.join(states_dir, name))
                removed.append(name)
            except Exception:
                LOGGER.error(f"Could not remove '{name}'.", exc_info=True)
        if removed:
            LOGGER.info(
                f"Pruned {len(removed)} timestamped queue export(s), keeping the "
                f"newest {keep}: removed {removed[0]}..{removed[-1]}"
                if len(removed) > 1
                else f"Pruned 1 timestamped queue export, keeping the newest "
                f"{keep}: removed {removed[0]}"
            )
        return removed

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
            try:
                with open(save_path, "rb") as f:
                    queue_dict = pickle.load(f)
            except Exception:
                # A pickle written by an older release can reference classes this
                # one no longer has (e.g. a renamed model), and unpickling raises
                # AttributeError. This runs inside the orchestrator's FastAPI
                # startup_event, so an escape here fails the lifespan and the
                # server exits instead of coming up -- a stale file on disk must
                # not be able to keep the orchestrator down. Quarantine it so the
                # next startup is clean rather than repeating the same failure.
                quarantine = save_path.replace(
                    ".pck",
                    f"_unreadable_{datetime.now().strftime('%y%m%d.%H%M%S')}.pck",
                )
                try:
                    os.rename(save_path, quarantine)
                    moved = f"moved it to '{os.path.basename(quarantine)}'"
                except Exception:
                    moved = "could not move it aside"
                LOGGER.error(
                    f"Could not unpickle '{save_path}' -- it was most likely "
                    f"written by a different code version; {moved} and starting "
                    f"with empty queues.",
                    exc_info=True,
                )
                return save_path
        else:
            LOGGER.info("Exported queues.pck does not exist. Cannot restore.")
            return save_path
        # Layout check. The pickle loaded, so its class references all resolve;
        # what this catches is a payload whose shape this code cannot faithfully
        # restore. Pickles written before the schema stamp existed report None and
        # are declined for the same reason -- there is no way to confirm they match.
        found_schema = queue_dict.get("schema")
        if found_schema != QUEUE_PCK_SCHEMA:
            LOGGER.error(
                f"Refusing to restore '{save_path}': payload schema is "
                f"{found_schema!r} but this code writes and expects "
                f"{QUEUE_PCK_SCHEMA!r}. The file was written by a different "
                f"version; leaving it in place and starting with empty queues. "
                f"Delete it, or restore it deliberately with a build whose schema "
                f"matches."
            )
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
