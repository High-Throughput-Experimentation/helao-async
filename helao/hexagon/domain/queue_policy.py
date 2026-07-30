"""Pure queue-CRUD / run-id / process-group / plan-merge policies.

Extracted decision cores of RunQueues (helao/core/servers/orch_queues.py) and
DispatchRunner.dispatch_sequence/_expand_experiment_actions
(helao/core/servers/orch_dispatch.py). The zdeque objects and history maps
stay app-side (P1b); these functions make the decisions. UUID minting is
injected (``mint``) so tests are deterministic; production passes
helao.helpers.gen_uuid.gen_uuid through the composition root.
"""

from collections import defaultdict
from collections.abc import Callable
from collections.abc import Sequence as Seq
from typing import Optional
from uuid import UUID

from helao.hexagon.domain.models import (
    Action,
    Experiment,
    Sequence,
    ShortExperimentModel,
)

__all__ = [
    "assign_process_groups",
    "bump_retry",
    "ensure_run_id",
    "fold_sequence_onto_experiment",
    "merge_planned_experiments",
    "resolve_active_run_id",
]

UuidFactory = Callable[[], UUID]


def ensure_run_id(
    active_run_id: Optional[UUID],
    sequence_dq_empty: bool,
    mint: UuidFactory,
) -> UUID:
    """Run-id to stamp on a sequence entering the queue (orch_queues.py:125).

    Empty/just-cleared queue -> fresh run_id; non-empty -> reuse the in-flight
    active_run_id (back-to-back queue entries share a run).
    """
    if sequence_dq_empty or active_run_id is None:
        return mint()
    return active_run_id


def resolve_active_run_id(
    sequence_run_id: Optional[UUID],
    active_run_id: Optional[UUID],
) -> tuple[Optional[UUID], Optional[UUID]]:
    """At dequeue, sync run ids (orch_queues.py:136-142).

    Returns (run_id_for_sequence, new_active_run_id): the sequence's own
    run_id wins; else it inherits the orch's active_run_id; both None stays
    both None.
    """
    if sequence_run_id is not None:
        return sequence_run_id, sequence_run_id
    if active_run_id is not None:
        return active_run_id, active_run_id
    return None, None


def fold_sequence_onto_experiment(
    seq: Sequence,
    experimentmodel: object,
) -> Experiment:
    """The add_experiment field-fold (orch_queues.py:350-358), verbatim:
    validate into a runtime Experiment, then setattr every Sequence field.

    Minting experiment_uuid and defaulting the orchestrator identity remain
    the caller's job (they need the orch identity / uuid factory).
    """
    seq_dict = seq.model_dump()
    if not isinstance(experimentmodel, Experiment):
        experimentmodel_dict = experimentmodel.model_dump()  # type: ignore[attr-defined]
        D = Experiment.model_validate(experimentmodel_dict)
    else:
        D = experimentmodel
    for k in seq_dict.keys():
        setattr(D, k, getattr(seq, k))
    return D


def bump_retry(
    errored_action: Action,
    sup_action: Action,
    machine_name: str,
) -> Action:
    """supplement_error_action's counter surgery (orch_queues.py:464-469):
    copy order/actual_order from the errored action, bump retry, stamp the
    orch machine name. The head-appendleft stays with the caller."""
    new_action = sup_action
    new_action.action_order = errored_action.action_order
    new_action.action_actual_order = errored_action.action_actual_order
    new_action.action_retry = (errored_action.action_retry or 0) + 1
    new_action.action_server.machine_name = machine_name
    return new_action


def assign_process_groups(
    actions: Seq[Action],
    mint: UuidFactory,
) -> tuple[dict[int, list[int]], list[UUID]]:
    """Process grouping at experiment expansion (orch_dispatch.py:1124-1158).

    Mutates each contributing action's process_uuid in place (as legacy does)
    and returns (process_order_groups, process_list). The count-based
    truncation ``init_process_uuids[:len(process_order_groups)]`` is a legacy
    quirk reproduced deliberately (parity over intuition).
    """
    process_order_groups: dict[int, list[int]] = defaultdict(list)
    process_count = 0
    init_process_uuids = [mint()]
    for i, act in enumerate(actions):
        if act.process_contrib:
            process_order_groups[process_count].append(i)
            act.process_uuid = init_process_uuids[process_count]
        if act.process_finish:
            process_count += 1
            init_process_uuids.append(mint())
    if process_order_groups:
        process_list = init_process_uuids[: len(process_order_groups)]
        return dict(process_order_groups), process_list
    return {}, []


def merge_planned_experiments(
    operator_plan: list[ShortExperimentModel],
    fresh_plan: list[ShortExperimentModel],
) -> list[ShortExperimentModel]:
    """Planned-experiment merge at sequence dispatch (orch_dispatch.py:1264-1293).

    Empty operator plan -> fresh plan. Operator plan at least as long as the
    fresh plan -> walk pairwise; on name match fold the operator entry's
    fields onto the fresh entry; on mismatch break; adopt the merged list
    only when it kept the operator plan's full length. Anything else keeps
    the operator plan untouched.
    """
    if not operator_plan:
        return list(fresh_plan)
    if len(operator_plan) >= len(fresh_plan):
        remaining = list(fresh_plan)
        new_planned: list[ShortExperimentModel] = []
        for exp_model in operator_plan:
            if not remaining:
                new_planned.append(exp_model)
            else:
                exp = remaining.pop(0)
                if exp.experiment_name == exp_model.experiment_name:
                    for k, v in vars(exp_model).items():
                        setattr(exp, k, v)
                    new_planned.append(exp)
                else:
                    break
        if len(operator_plan) == len(new_planned):
            return new_planned
    return list(operator_plan)
