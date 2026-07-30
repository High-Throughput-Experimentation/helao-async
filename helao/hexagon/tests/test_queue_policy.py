"""Pure queue/run-id/process-group/plan-merge policies (core-01 §2/§3)."""

from itertools import count
from uuid import NAMESPACE_URL, UUID, uuid5

from helao.hexagon.domain import queue_policy as qp
from helao.hexagon.domain.models import (
    Action,
    ProcessContrib,
    Sequence,
    ShortExperimentModel,
)


def mk_uuid_factory():
    c = count()
    return lambda: uuid5(NAMESPACE_URL, f"test-{next(c)}")


# --- run-id policy (orch_queues.py:125-142) ---


def test_ensure_run_id_mints_when_queue_empty():
    mint = mk_uuid_factory()
    stale = mint()
    new = qp.ensure_run_id(active_run_id=stale, sequence_dq_empty=True, mint=mint)
    assert new != stale


def test_ensure_run_id_reuses_inflight_when_queue_nonempty():
    mint = mk_uuid_factory()
    inflight = mint()
    assert (
        qp.ensure_run_id(active_run_id=inflight, sequence_dq_empty=False, mint=mint)
        == inflight
    )


def test_resolve_active_run_id_sequence_wins():
    mint = mk_uuid_factory()
    seq_rid, orch_rid = mint(), mint()
    new_seq, new_active = qp.resolve_active_run_id(seq_rid, orch_rid)
    assert new_active == seq_rid and new_seq == seq_rid


def test_resolve_active_run_id_inherits_orch_when_sequence_unset():
    mint = mk_uuid_factory()
    orch_rid = mint()
    new_seq, new_active = qp.resolve_active_run_id(None, orch_rid)
    assert new_seq == orch_rid and new_active == orch_rid


def test_resolve_active_run_id_both_none():
    assert qp.resolve_active_run_id(None, None) == (None, None)


# --- add_experiment field-fold (orch_queues.py:350-358) ---


def test_fold_sequence_onto_experiment_setattr_loop():
    seq = Sequence(sequence_name="s", sequence_label="lab", sequence_params={"a": 1})
    exp = qp.fold_sequence_onto_experiment(
        seq, ShortExperimentModel(experiment_name="e", experiment_params={"p": 2})
    )
    # every Sequence model field is folded onto the experiment
    assert exp.sequence_name == "s"
    assert exp.sequence_label == "lab"
    assert exp.sequence_params == {"a": 1}
    # experiment identity minted fresh is the CALLER's job (add_experiment
    # mints after the fold); the fold itself must not set experiment_uuid
    assert exp.experiment_name == "e"


# --- supplement_error_action retry bump (orch_queues.py:445-470) ---


def test_bump_retry_copies_orders_and_increments_retry():
    errored = Action(action_name="a")
    errored.action_order = 4
    errored.action_actual_order = 7
    errored.action_retry = 1
    sup = Action(action_name="a")
    out = qp.bump_retry(errored, sup, machine_name="orchbox")
    assert out.action_order == 4
    assert out.action_actual_order == 7
    assert out.action_retry == 2
    assert out.action_server.machine_name == "orchbox"


# --- process grouping (orch_dispatch.py:1124-1158) ---


def _acts(spec):
    """spec: list of (contrib: bool, finish: bool)."""
    acts = []
    for contrib, finish in spec:
        a = Action(action_name="x")
        if contrib:
            a.process_contrib = [ProcessContrib.files]
        a.process_finish = finish
        acts.append(a)
    return acts


def test_assign_process_groups_two_groups():
    mint = mk_uuid_factory()
    acts = _acts([(True, False), (True, True), (True, False), (True, True)])
    groups, process_list = qp.assign_process_groups(acts, mint)
    assert groups == {0: [0, 1], 1: [2, 3]}
    assert len(process_list) == 2
    # every contributing action got its group's uuid stamped
    assert acts[0].process_uuid == acts[1].process_uuid == process_list[0]
    assert acts[2].process_uuid == acts[3].process_uuid == process_list[1]


def test_assign_process_groups_no_contrib_no_groups():
    mint = mk_uuid_factory()
    acts = _acts([(False, False), (False, False)])
    groups, process_list = qp.assign_process_groups(acts, mint)
    assert groups == {} and process_list == []


def test_assign_process_groups_truncation_quirk_preserved():
    """Legacy: process_list = init_process_uuids[:len(process_order_groups)].
    With a finish-only action (no contrib) between groups, the group indices
    are non-contiguous but the uuid list is truncated by COUNT — reproduce
    exactly (parity over intuition)."""
    mint = mk_uuid_factory()
    acts = _acts([(True, True), (False, True), (True, True)])
    groups, process_list = qp.assign_process_groups(acts, mint)
    assert sorted(groups.keys()) == [0, 2]
    assert len(process_list) == 2  # count-truncated, NOT index-selected


# --- planned-experiment merge (orch_dispatch.py:1264-1293) ---


def _plan(*names):
    return [ShortExperimentModel(experiment_name=n) for n in names]


def test_merge_uses_fresh_plan_when_operator_plan_empty():
    fresh = _plan("a", "b")
    assert qp.merge_planned_experiments([], fresh) == fresh


def test_merge_prefix_match_folds_operator_fields_onto_fresh():
    operator = _plan("a", "b", "c")
    operator[1].experiment_params = {"tweaked": True}
    fresh = _plan("a", "b")
    merged = qp.merge_planned_experiments(operator, fresh)
    # operator plan longer + prefix-matches -> merged keeps operator length
    assert [e.experiment_name for e in merged] == ["a", "b", "c"]
    assert merged[1].experiment_params == {"tweaked": True}


def test_merge_name_mismatch_keeps_operator_plan():
    operator = _plan("a", "X", "c")
    fresh = _plan("a", "b")
    merged = qp.merge_planned_experiments(operator, fresh)
    # break on mismatch -> lengths differ -> operator plan retained verbatim
    assert merged == operator


def test_merge_shorter_operator_plan_keeps_operator_plan():
    operator = _plan("a")
    fresh = _plan("a", "b")
    assert qp.merge_planned_experiments(operator, fresh) == operator
