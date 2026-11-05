"""Queue-persistence collaborator extracted from ``Orch`` (CARDS P5, Stage S2).

``Orch.export_queues``/``Orch.import_queues`` pickle (respectively restore) the
run deques, active/last sequence and experiment, the global status model, and
the action/experiment/sequence histories. This module builds that payload and
applies it back onto the orchestrator; the file itself -- ``STATES/queues.pck``,
the timestamped series and its pruning, the ``_unreadable_`` quarantine and the
``_imported_`` archive -- belongs to the ``StatePersistencePort``
(``adapters/shared/state_persistence.py``, resolved from
``orch.hexagon_wiring.state_persistence`` at call time).

Per the P5 constraints (:doc:`CARDS_REFACTOR_P5.md` sec 3.1 rule 3):
``import_queues`` *reassigns* ``globalstatusmodel``, ``active_*``, ``last_*``,
and the history deques, and ``loop_task_dispatch_experiment`` (``orch.py:933``)
separately reassigns ``action_dq``. ``QueuePersister`` therefore caches no
shared mutable state -- it holds only the ``orch`` back-reference and reads
every deque/attribute (and the port) through it at call time, so a
reassignment made between construction and a call (or between two calls) is
always observed. Behavior is byte-identical to the original inline methods:
same pickle payload dict (keys and value types), same file path
(``STATES/queues.pck``), same timestamped-filename variant, and the same
restored-file archival (``queues_imported_<ts>.pck``).

Pickle safety: the payload dict pickled by :meth:`export_queues` contains only
plain model instances and list/dict data -- never a ``QueuePersister``
instance or any other collaborator -- so a ``queues.pck`` written before this
stage still imports cleanly after it, and vice versa.
"""

from copy import deepcopy
from typing import Optional

from helao.core.models.hlostatus import HloStatus
from helao.core.models.orchstatus import LoopIntent, LoopStatus
from helao.helpers import helao_logging as logging
from helao.helpers.dequedict import DequeDict
from helao.helpers.premodels import Action
from helao.helpers.time_utils import gen_uuid
from helao.hexagon.adapters.shared.state_persistence import (  # noqa: F401  (re-exported)
    _TIMESTAMPED_EXPORT_RE,
    TIMESTAMPED_EXPORT_RETENTION,
)

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

# Action fields the orchestrator or action server fills in while an action runs;
# a re-run copy gets them back at the model default so it dispatches as new.
_RUNTIME_ACTION_FIELDS = (
    "action_uuid",
    "action_timestamp",
    "action_status",
    "action_output_dir",
    "action_output",
    "action_finished_timestamp",
    "orch_submit_order",
    "files",
    "file_conn_keys",
    "data_stream_status",
    "error_code",
    "samples_out",
    "parent_action_uuid",
    "child_action_uuid",
    "prefinish_errors",
)

# What the live status copy of an in-flight action lacks: dispatch fills the
# sequence/experiment linkage onto queued actions at plan time, never onto the copy
# an action server reports. Without it ``init_act`` sees no sequence timestamp and
# re-runs the action as a manual one, under DIAG, outside every process.
_SEQUENCE_LINK_FIELDS = (
    "sequence_uuid",
    "sequence_name",
    "sequence_label",
    "sequence_timestamp",
    "sequence_params",
    "sequence_output_dir",
    "sequence_status",
    "planned_experiments",
)
_EXPERIMENT_LINK_FIELDS = (
    "experiment_name",
    "experiment_params",
    "experiment_output_dir",
    "experiment_status",
)


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
        can decline a layout it cannot restore. The port writes the file; when
        ``timestamp_pck`` is set it also prunes the timestamped series to
        :data:`TIMESTAMPED_EXPORT_RETENTION` files.

        Args:
            timestamp_pck: When True, embed a timestamp in the pickle filename.

        Returns:
            Filesystem path of the written pickle file.
        """
        orch = self.orch
        acts = list(orch.action_dq)
        if orch.parked_head_action is not None:
            acts.insert(0, orch.parked_head_action)
        queue_dict = {
            "schema": QUEUE_PCK_SCHEMA,
            "seq": list(orch.sequence_dq),
            "exp": list(orch.experiment_dq),
            "act": acts,
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
        return self.orch.hexagon_wiring.state_persistence.export_queues(
            queue_dict, timestamp_pck
        )

    def _requeue_inflight_actions(self) -> None:
        """Re-run, under a fresh uuid, every action that was in flight at export.

        The new process's action servers never report the old uuids, so left in
        ``active_dict`` they keep ``actions_idle()`` false forever and hang every
        wait-for-all, experiment close-out and stop drain. Each one is retired to
        ``skipped`` (not ``errored``, which trips the errored-uuid ingestion) and a
        fresh copy goes to the front of ``action_dq`` in the original order. The
        retry keeps ``action_order`` and bumps ``action_retry``, as an errored-action
        retry does. ``counter_dispatched_actions`` is left alone: the interrupted
        attempt keeps its ``orch_submit_order``, so the re-run takes the next one and
        the two run directories cannot collide.
        """
        orch = self.orch
        gsm = orch.globalstatusmodel
        inflight = dict(gsm.active_dict)
        for srv in gsm.server_dict.values():
            for ep in srv.endpoints.values():
                for uuid, act in ep.active_dict.items():
                    inflight.setdefault(uuid, act)
        if not inflight:
            return
        exp = orch.active_experiment
        exp_uuid = exp.experiment_uuid if exp is not None else None
        fresh = []
        for uuid, act in sorted(
            inflight.items(), key=lambda kv: kv[1].orch_submit_order or 0
        ):
            if exp_uuid is None or act.experiment_uuid != exp_uuid:
                LOGGER.warning(
                    f"In-flight action {act.action_name} ({uuid}) does not belong to "
                    "the restored active experiment; retiring it without a re-run."
                )
            else:
                new = act.model_copy(deep=True)
                for name in _RUNTIME_ACTION_FIELDS:
                    setattr(
                        new,
                        name,
                        Action.model_fields[name].get_default(
                            call_default_factory=True
                        ),
                    )
                # Experiment subclasses Sequence, so it can stand in for it
                seq = orch.active_sequence or exp
                for src, names in (
                    (seq, _SEQUENCE_LINK_FIELDS),
                    (exp, _EXPERIMENT_LINK_FIELDS),
                ):
                    if src is not None:
                        for name in names:
                            setattr(new, name, deepcopy(getattr(src, name)))
                new.action_retry = (act.action_retry or 0) + 1
                fresh.append(new)
            # retire the old uuid: the experiment record shows the attempt as
            # [skipped, finished]. The killed server's on-disk -act.yml reads
            # active until that action server's next startup, when
            # ActionHost.reconcile_interrupted() finalizes it [finished, errored]
            # and hands it to the syncer (the experiment syncs only after that).
            act.action_status = [HloStatus.skipped, HloStatus.finished]
            for d in [gsm.active_dict] + [
                e.active_dict
                for srv in gsm.server_dict.values()
                for e in srv.endpoints.values()
            ]:
                d.pop(uuid, None)
            gsm.nonactive_dict.setdefault(HloStatus.skipped, {})[uuid] = act
            for srv in gsm.server_dict.values():
                ep = srv.endpoints.get(act.action_name)
                if ep is not None and srv.action_server.server_name == (
                    act.action_server.server_name
                ):
                    ep.nonactive_dict.setdefault(HloStatus.skipped, {})[uuid] = act
            if exp is not None:
                for d in exp.dispatched_actions:
                    if d.action_uuid == uuid:
                        d.action_status = [HloStatus.skipped, HloStatus.finished]
            # both would otherwise point wait_for_previous / the history poll
            # at an action that will never be acknowledged
            if str(orch.last_action_uuid) == str(uuid):
                orch.last_action_uuid = ""
            if str(orch.last_dispatched_action_uuid) == str(uuid):
                orch.last_dispatched_action_uuid = None
        for new in reversed(fresh):
            orch.action_dq.appendleft(new)
        LOGGER.info(
            f"Re-queued {len(fresh)} action(s) that were in flight at export; "
            f"retired {len(inflight)} old uuid(s) to skipped."
        )

    def import_queues(self, pck_path: Optional[str] = None) -> str:
        """Restore deques/active/last state from a previously exported pickle.

        Args:
            pck_path: Optional explicit path to the pickle; defaults to
                ``<root>/STATES/queues.pck``.

        Returns:
            The path that was loaded (or attempted).
        """
        orch = self.orch
        store = orch.hexagon_wiring.state_persistence
        save_path, queue_dict = store.load_queues(pck_path)
        if queue_dict is None:
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
                orch.seq_model = (
                    orch.active_sequence.get_seq() if orch.active_sequence else None
                )
                orch.last_sequence = queue_dict["last_seq"]
                orch.active_seq_exp_counter = queue_dict["active_counter"]
                orch.last_action_uuid = queue_dict["last_act"]
                orch.last_dispatched_action_uuid = queue_dict["last_dispatched_act"]
                orch.globalstatusmodel = queue_dict["globalstatusmodel"]
                # The dispatch loop does not survive a restart, so its flags must
                # not either: a pickle written mid-run holds loop_state=started,
                # which `start` treats as already running -- nothing would ever
                # dispatch. loop_state=estopped is the E-STOP latch (cleared only
                # by /clear_estop) and is kept; nothing produces an estop *intent*.
                gsm = orch.globalstatusmodel
                if gsm.loop_state != LoopStatus.estopped:
                    gsm.loop_state = LoopStatus.stopped
                gsm.loop_intent = LoopIntent.none
                self._requeue_inflight_actions()
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
                    # An explicitly-pathed restore is left untouched (the caller
                    # chose it deliberately); the default file is archived so a
                    # stale one cannot be auto-replayed on a later restart.
                    store.archive_consumed(save_path)
            except Exception:
                LOGGER.warning(
                    "Error restoring queues from pck. Check if pck is compatible.",
                    exc_info=True,
                )
        return save_path
