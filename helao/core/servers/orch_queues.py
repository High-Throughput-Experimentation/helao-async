"""RunQueues -- cluster A: queue CRUD, uuid tracking, run-id/meta helpers
extracted from ``Orch`` (CARDS P5, Stage S5).

``Orch.register_obj_uuid``/``register_action_uuid``/``track_action_uuid``,
the run-id/meta helpers (``_prep_sequence_meta``/``_ensure_run_id``/
``_resolve_active_run_id``), the add/rebuild/move/remove/list/get methods for
the sequence/experiment/action deques, and the action-edit helpers
(``supplement_error_action``/``replace_action``/``append_action``) plus the
``clear_sequences``/``clear_experiments``/``clear_actions`` trio implement the
orchestrator's "cluster A": CRUD over the three run queues and the uuid
history maps. This module moves those 32 method bodies into a ``RunQueues``
collaborator that ``Orch`` delegates to.

Per the P5 constraints (:doc:`CARDS_REFACTOR_P5.md` sec 3.1 rule 3):
``RunQueues`` caches no shared mutable state -- it holds only the ``orch``
back-reference and reads/writes ``sequence_dq``/``experiment_dq``/
``action_dq``, the uuid trackers (``action_history``/``experiment_history``/
``sequence_history``/``last_dispatched_action_uuid``), ``active_run_id``,
``active_experiment``/``active_sequence``/``last_experiment``/
``last_sequence``, ``globalstatusmodel``, and the sequence/experiment
library maps through ``orch`` at call time, so a reassignment made between
construction and a call (e.g. ``import_queues`` reassigning the deques) is
always observed. Behavior is byte-identical to the original inline methods.

``sanitize_sequence_label`` stays a module-level function on ``orch.py`` (its
single home); ``_prep_sequence_meta`` and ``add_split_sequences`` reach it via
a lazy import inside the method body to avoid a circular import (``orch.py``
imports this module at module top).
"""

import asyncio
from copy import deepcopy
from typing import List, Optional
from uuid import UUID

from helao.helpers import helao_logging as logging
from helao.helpers.time_utils import gen_uuid
from helao.core.models.hlostatus import HloStatus
from helao.core.models.experiment import ExperimentModel, ShortExperimentModel
from helao.helpers.premodels import Sequence, Experiment, Action

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class RunQueues:
    """Queue-CRUD and uuid-tracking methods for an ``Orch``.

    Holds only the ``orch`` back-reference (never a cached deque/attribute),
    per the call-time state resolution rule -- see module docstring.
    """

    def __init__(self, orch):
        self.orch = orch

    def register_obj_uuid(self, obj_uuid_key, obj_uuid_dict, obj_type: str):
        """Insert or merge a UUID's metadata into the action/experiment/sequence history map.

        Args:
            obj_uuid_key: UUID of the action, experiment, or sequence.
            obj_uuid_dict: Metadata associated with the UUID.
            obj_type: One of ``"action"``, ``"experiment"``, or ``"sequence"``.
        """
        orch = self.orch
        OBJ_MAP = {
            "action": orch.action_history,
            "experiment": orch.experiment_history,
            "sequence": orch.sequence_history,
        }

        if obj_uuid_key in OBJ_MAP[obj_type].keys():
            OBJ_MAP[obj_type][obj_uuid_key].update(obj_uuid_dict)
        else:
            OBJ_MAP[obj_type][obj_uuid_key] = obj_uuid_dict

    def register_action_uuid(self, action_uuid, action_dict):
        """Record an action UUID and its metadata in the action history map."""
        orch = self.orch
        orch.register_obj_uuid(action_uuid, action_dict, "action")

    def track_action_uuid(self, action_uuid):
        """Remember ``action_uuid`` as the most recently dispatched action."""
        orch = self.orch
        orch.last_dispatched_action_uuid = action_uuid

    async def clear_sequences(self):
        """Empty the sequence deque."""
        orch = self.orch
        LOGGER.info("clearing sequence queue")
        orch.sequence_dq.clear()

    async def clear_experiments(self):
        """Empty the experiment deque."""
        orch = self.orch
        LOGGER.info("clearing experiment queue")
        orch.experiment_dq.clear()

    async def clear_actions(self):
        """Empty the action deque."""
        orch = self.orch
        LOGGER.info("clearing action queue")
        orch.action_dq.clear()

    def _prep_sequence_meta(self, sequence: Sequence) -> None:
        """Populate uuid/codehash/codepath/funcname metadata on ``sequence`` in place."""
        orch = self.orch
        from helao.core.servers.orch import sanitize_sequence_label

        if sequence.sequence_uuid is None:
            sequence.sequence_uuid = gen_uuid()
        if (
            sequence.sequence_codehash is None
            and sequence.sequence_name in orch.sequence_codehash_lib
        ):
            sequence.sequence_codehash = orch.sequence_codehash_lib[
                sequence.sequence_name
            ]
            sequence.sequence_codepath = orch.sequence_codepath_lib[
                sequence.sequence_name
            ]
            sequence.sequence_funcname = orch.sequence_lib[
                sequence.sequence_name
            ].__name__
        sequence.sequence_label = sanitize_sequence_label(sequence.sequence_label)

    def _ensure_run_id(self) -> UUID:
        """Return the run_id to stamp on a sequence entering the queue.

        Empty/just-cleared queue -> fresh run_id; non-empty -> reuse the
        in-flight ``active_run_id`` (back-to-back sharing).
        """
        orch = self.orch
        if len(orch.sequence_dq) == 0:
            orch.active_run_id = gen_uuid()
        return orch.active_run_id

    def _resolve_active_run_id(self, sequence: Sequence) -> None:
        """At dequeue, sync ``active_run_id`` with the active sequence's run_id."""
        orch = self.orch
        if sequence.run_id is not None:
            orch.active_run_id = sequence.run_id
        elif orch.active_run_id is not None:
            sequence.run_id = orch.active_run_id

    async def add_sequence(self, sequence: Sequence) -> UUID:
        """Append ``sequence`` to the sequence deque, populating its metadata and run_id.

        Returns:
            The UUID of the added sequence.
        """
        orch = self.orch
        orch._prep_sequence_meta(sequence)
        sequence.run_id = orch._ensure_run_id()
        orch.sequence_dq.append(sequence)
        return sequence.sequence_uuid

    async def add_split_sequences(self, sequence: Sequence):
        """Split ``sequence`` along the configured params and enqueue each sub-sequence.

        Args:
            sequence: Source sequence whose parameters trigger splitting.

        Returns:
            List of sub-sequence UUIDs, or the result of :meth:`add_sequence`
            if no split parameter applied.
        """
        orch = self.orch
        from helao.core.servers.orch import sanitize_sequence_label

        possible_splits = [
            x
            for x in sequence.sequence_params
            if x in orch.server_params.get("split_by_seq_params", [])
        ]
        possible_groups = [
            x
            for x in sequence.sequence_params
            if x in orch.server_params.get("group_by_seq_params", [])
        ]

        if possible_splits:
            run_id = orch._ensure_run_id()
            split_key = possible_splits[0]
            split_list = sequence.sequence_params[split_key]
            sub_sequence_uuids = []
            if possible_groups:
                group_key = possible_groups[0]
                group_list = sequence.sequence_params[group_key]
                run_seq_param = group_key
            else:
                group_list = split_list
                run_seq_param = split_key
            sub_sequence_items = []
            for i, item in enumerate(split_list):
                sub_sequence_items.append(item)
                if item in group_list or i == len(split_list) - 1:
                    # create a copy of the sequence
                    sub_sequence = deepcopy(sequence)
                    sub_sequence.sequence_label = sanitize_sequence_label(
                        sub_sequence.sequence_label
                    )
                    # set the plate_sample_no in the params
                    sub_sequence.sequence_params[split_key] = sub_sequence_items
                    # generate new sub_sequence uuid
                    sub_sequence.sequence_uuid = gen_uuid()
                    # Clear planned experiments to ensure they regenerate when the sub-sequence is dequeued.
                    sub_sequence.planned_experiments.clear()
                    if (
                        sub_sequence.sequence_codehash is None
                        and sub_sequence.sequence_name in orch.sequence_codehash_lib
                    ):
                        sub_sequence.sequence_codehash = orch.sequence_codehash_lib[
                            sub_sequence.sequence_name
                        ]
                        sub_sequence.sequence_codepath = orch.sequence_codepath_lib[
                            sub_sequence.sequence_name
                        ]
                        sub_sequence.sequence_funcname = orch.sequence_lib[
                            sub_sequence.sequence_name
                        ].__name__
                    sub_sequence.run_sequence_parameter_variable = [run_seq_param]
                    sub_sequence.run_id = run_id
                    orch.sequence_dq.append(sub_sequence)
                    sub_sequence_uuids.append(sub_sequence.sequence_uuid)
                    sub_sequence_items = []
            return sub_sequence_uuids
        else:
            return await orch.add_sequence(sequence)

    async def prepend_sequences(self, sequences: List[Sequence]) -> List[UUID]:
        """Insert ``sequences`` at the front of the queue, preserving their order.

        Stamps uuid/codehash/run_id like :meth:`add_sequence`. Reuses the
        in-flight run_id when the queue is non-empty, else mints a fresh one.
        An empty list is a no-op (returns ``[]`` without touching run_id).

        Returns:
            The UUIDs of the prepended sequences, in buffer order.
        """
        orch = self.orch
        if not sequences:
            return []
        run_id = orch._ensure_run_id()
        uuids = []
        for i, sequence in enumerate(sequences):
            orch._prep_sequence_meta(sequence)
            sequence.run_id = run_id
            orch.sequence_dq.insert(i, sequence)
            uuids.append(sequence.sequence_uuid)
        return uuids

    def _rebuild_sequence_dq(self, seqs) -> None:
        """Replace the sequence deque contents with ``seqs`` (re-compresses each)."""
        orch = self.orch
        orch.sequence_dq.clear()
        for s in seqs:
            orch.sequence_dq.append(s)

    async def move_sequence(self, from_idx: int, to_idx: int) -> None:
        """Move the queued sequence at ``from_idx`` to ``to_idx`` (no-op if out of range)."""
        orch = self.orch
        seqs = list(orch.sequence_dq)
        n = len(seqs)
        if 0 <= from_idx < n and 0 <= to_idx < n:
            seq = seqs.pop(from_idx)
            seqs.insert(to_idx, seq)
            orch._rebuild_sequence_dq(seqs)

    async def remove_sequence(self, idx: int) -> None:
        """Remove the queued sequence at ``idx`` (no-op if out of range)."""
        orch = self.orch
        seqs = list(orch.sequence_dq)
        if 0 <= idx < len(seqs):
            seqs.pop(idx)
            orch._rebuild_sequence_dq(seqs)

    def _rebuild_experiment_dq(self, exps) -> None:
        """Replace the experiment deque contents with ``exps`` (re-compresses each)."""
        orch = self.orch
        orch.experiment_dq.clear()
        for e in exps:
            orch.experiment_dq.append(e)

    async def move_experiment(self, from_idx: int, to_idx: int) -> None:
        """Move the queued experiment at ``from_idx`` to ``to_idx`` (no-op if out of range)."""
        orch = self.orch
        exps = list(orch.experiment_dq)
        n = len(exps)
        if 0 <= from_idx < n and 0 <= to_idx < n:
            exp = exps.pop(from_idx)
            exps.insert(to_idx, exp)
            orch._rebuild_experiment_dq(exps)

    async def remove_experiment(
        self, idx: Optional[int] = None, by_uuid: Optional[UUID] = None
    ) -> None:
        """Remove the queued experiment at ``idx`` (or matching ``by_uuid``); no-op if out of range."""
        orch = self.orch
        exps = list(orch.experiment_dq)
        if by_uuid is not None:
            idx = next(
                (i for i, e in enumerate(exps) if e.experiment_uuid == by_uuid), None
            )
        if idx is not None and 0 <= idx < len(exps):
            exps.pop(idx)
            orch._rebuild_experiment_dq(exps)

    def _rebuild_action_dq(self, acts) -> None:
        """Replace the action deque contents with ``acts`` (re-compresses each)."""
        orch = self.orch
        orch.action_dq.clear()
        for a in acts:
            orch.action_dq.append(a)

    async def move_action(self, from_idx: int, to_idx: int) -> None:
        """Move the queued action at ``from_idx`` to ``to_idx`` (no-op if out of range)."""
        orch = self.orch
        acts = list(orch.action_dq)
        n = len(acts)
        if 0 <= from_idx < n and 0 <= to_idx < n:
            act = acts.pop(from_idx)
            acts.insert(to_idx, act)
            orch._rebuild_action_dq(acts)

    async def remove_action(self, idx: int) -> None:
        """Remove the queued action at ``idx`` (no-op if out of range)."""
        orch = self.orch
        acts = list(orch.action_dq)
        if 0 <= idx < len(acts):
            acts.pop(idx)
            orch._rebuild_action_dq(acts)

    async def add_experiment(
        self,
        seq: Sequence,
        experimentmodel: Experiment | ExperimentModel | ShortExperimentModel,
        prepend: bool = False,
        at_index: Optional[int] = None,
    ) -> UUID:
        """Enqueue an experiment derived from ``experimentmodel`` and attached to ``seq``.

        Args:
            seq: Sequence whose fields are folded into the new experiment.
            experimentmodel: Experiment definition to enqueue.
            prepend: If True, push to the front of the deque.
            at_index: Optional index to insert at; takes precedence over ``prepend``.

        Returns:
            The UUID of the enqueued experiment.
        """
        orch = self.orch
        seq_dict = seq.model_dump()
        if not isinstance(experimentmodel, Experiment):
            experimentmodel_dict = experimentmodel.model_dump()
            D = Experiment.model_validate(experimentmodel_dict)
        else:
            D = experimentmodel
        for k in seq_dict.keys():
            setattr(D, k, getattr(seq, k))

        # init uuid now for tracking later
        D.experiment_uuid = gen_uuid()

        # reminder: experiment_dict values take precedence over keyword args
        if D.orchestrator.server_name is None or D.orchestrator.machine_name is None:
            D.orchestrator = orch.server

        await asyncio.sleep(0.01)
        if at_index is not None:
            orch.experiment_dq.insert(i=at_index, x=D)
        elif prepend:
            orch.experiment_dq.appendleft(D)
            # LOGGER.info(f"experiment {D.experiment_name} prepended to queue")
        else:
            orch.experiment_dq.append(D)
            # LOGGER.info(f"experiment {D.experiment_name} appended to queue")
        return D.experiment_uuid

    def list_sequences(self, limit=10) -> list:
        """Return at most ``limit`` sequence summaries from the sequence deque."""
        orch = self.orch
        return [
            orch.sequence_dq[i].get_seq()
            for i in range(min(len(orch.sequence_dq), limit))
        ]

    def list_experiments(self, limit=10) -> list:
        """Return at most ``limit`` experiment summaries from the experiment deque."""
        orch = self.orch
        return [
            orch.experiment_dq[i].get_exp()
            for i in range(min(len(orch.experiment_dq), limit))
        ]

    def list_all_experiments(self) -> list:
        """Return ``(index, experiment_name)`` tuples for every queued experiment."""
        orch = self.orch
        return [
            (i, D.get_exp().experiment_name) for i, D in enumerate(orch.experiment_dq)
        ]

    def drop_experiment_inds(self, inds: List[int]) -> list:
        """Remove the queued experiments at ``inds`` and return :meth:`list_all_experiments`."""
        orch = self.orch
        for i in sorted(inds, reverse=True):
            del orch.experiment_dq[i]
        return orch.list_all_experiments()

    def get_experiment(self, last=False) -> Experiment:
        """Return the active (or, if ``last`` is True, most recent) experiment summary.

        Returns an empty dict when no experiment is available.
        """
        orch = self.orch
        experiment = orch.last_experiment if last else orch.active_experiment
        if experiment is not None:
            return experiment.get_exp()
        return {}

    def get_sequence(self, last=False) -> Sequence:
        """Return the active (or, if ``last`` is True, most recent) sequence summary.

        Returns an empty dict when no sequence is available.
        """
        orch = self.orch
        sequence = orch.last_sequence if last else orch.active_sequence
        if sequence is not None:
            return sequence.get_seq()
        return {}

    def list_active_actions(self) -> list:
        """Return the status model entries for every currently active action."""
        orch = self.orch
        return [
            statusmodel
            for uuid, statusmodel in orch.globalstatusmodel.active_dict.items()
        ]

    def list_actions(self, limit=10) -> list:
        """Return at most ``limit`` action summaries from the action deque."""
        orch = self.orch
        return [
            orch.action_dq[i].get_act() for i in range(min(len(orch.action_dq), limit))
        ]

    def supplement_error_action(self, check_uuid: UUID, sup_action: Action):
        """Retry an errored action by appending ``sup_action`` to the front of ``action_dq``.

        Args:
            check_uuid: UUID of the previously errored action.
            sup_action: Replacement action whose order/retry counters get adjusted.
        """
        orch = self.orch

        error_uuids = orch.globalstatusmodel.find_hlostatus_in_finished(
            hlostatus=HloStatus.errored,
        )
        if not error_uuids:
            LOGGER.info("There are no error statuses to replace")
        else:
            if check_uuid in error_uuids:
                EA_act = error_uuids[check_uuid]
                # sup_action can be a differnt one,
                # but for now we treat it thats a retry of the errored one
                new_action = sup_action
                new_action.action_order = EA_act.action_order
                # will be updated again once its dispatched again
                new_action.action_actual_order = EA_act.action_actual_order
                new_action.action_retry = EA_act.action_retry + 1
                new_action.action_server.machine_name = orch.server.machine_name
                orch.action_dq.appendleft(new_action)
            else:
                LOGGER.info(f"uuid {check_uuid} not found in list of error statuses:")
                LOGGER.info(", ")

    def replace_action(
        self,
        sup_action: Action,
        by_index: Optional[int] = None,
        by_uuid: Optional[UUID] = None,
        by_action_order: Optional[int] = None,
    ):
        """Replace a queued action selected by index, UUID, or action order with ``sup_action``."""
        orch = self.orch
        if by_index:
            i = by_index
        elif by_uuid:
            i = [
                i
                for i, A in enumerate(list(orch.action_dq))
                if A.action_uuid == by_uuid
            ][0]
        elif by_action_order:
            i = [
                i
                for i, A in enumerate(list(orch.action_dq))
                if A.action_order == by_action_order
            ][0]
        else:
            LOGGER.info("No arguments given for locating existing action to replace.")
            return None
        # get action_order of selected action which gets replaced
        current_action_order = orch.action_dq[i].action_order
        new_action = sup_action
        new_action.action_order = current_action_order
        new_action.action_server.machine_name = orch.server.machine_name
        orch.action_dq.insert(i, new_action)
        del orch.action_dq[i + 1]

    def append_action(self, sup_action: Action):
        """Append ``sup_action`` to ``action_dq`` and assign it the next action order."""
        orch = self.orch
        if len(orch.action_dq) == 0:
            last_action_order = (
                orch.globalstatusmodel.counter_dispatched_actions[
                    orch.active_experiment.experiment_uuid
                ]
                - 1
            )
            if last_action_order < 0:
                # no action was dispatched yet
                last_action_order = 0
        else:
            last_action_order = orch.action_dq[-1].action_order

        new_action_order = last_action_order + 1
        new_action = sup_action
        new_action.action_uuid = gen_uuid()
        new_action.action_order = new_action_order
        new_action.action_server.machine_name = orch.server.machine_name
        orch.action_dq.append(new_action)
