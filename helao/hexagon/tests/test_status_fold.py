"""Status-ingestion fold + the §4.2.4 side-effect checklist (core-01 §4)."""

from uuid import uuid4

from helao.hexagon.domain.status_fold import (
    PushLiveBuffer,
    RegisterHistoryEntry,
    SetOrchStateError,
    TriggerEstopFromStatus,
    WakeDispatchLoop,
    fold_status,
)
from helao.hexagon.domain.models import (
    Action,
    ActionServerModel,
    EndpointModel,
    GlobalStatusModel,
    HloStatus,
    MachineModel,
    OrchStatus,
)

ORCH_ID = MachineModel(server_name="ORCH", machine_name="orchbox")


def _asm(action: Action, endpoint: str, finished: bool) -> ActionServerModel:
    action_uuid = action.action_uuid
    assert action_uuid is not None
    asm = ActionServerModel(
        action_server=action.action_server,
        endpoints={endpoint: EndpointModel(endpoint_name=endpoint)},
        last_action_uuid=action_uuid,
    )
    if finished:
        asm.endpoints[endpoint].active_dict = {}
        asm.endpoints[endpoint].nonactive_dict = {
            HloStatus.finished: {action_uuid: action}
        }
    else:
        asm.endpoints[endpoint].active_dict = {action_uuid: action}
    return asm


def _action(status, orch=ORCH_ID) -> Action:
    act = Action(action_name="acquire")
    act.action_uuid = uuid4()
    act.action_server = MachineModel(server_name="SIM", machine_name="simbox")
    act.orchestrator = orch
    act.action_status = list(status)
    return act


def _gsm() -> GlobalStatusModel:
    return GlobalStatusModel(orchestrator=ORCH_ID)


def test_fold_always_wakes_dispatch_loop():
    gsm = _gsm()
    act = _action([HloStatus.active])
    _, cmds = fold_status(
        gsm,
        _asm(act, "acquire", finished=False),
        loop_started=False,
        last_dispatched_action_uuid=None,
    )
    assert any(isinstance(c, WakeDispatchLoop) for c in cmds)  # checklist #5


def test_history_registered_on_last_action_uuid_match():
    gsm = _gsm()
    act = _action([HloStatus.finished])
    asm = _asm(act, "acquire", finished=True)
    _, cmds = fold_status(
        gsm,
        asm,
        loop_started=True,
        last_dispatched_action_uuid=act.action_uuid,
    )
    hits = [c for c in cmds if isinstance(c, RegisterHistoryEntry)]
    assert hits and hits[0].action_uuid == act.action_uuid  # checklist #1


def test_history_not_registered_while_action_still_active():
    """FIX: ActionServerModel.last_action_uuid is set on every status push,
    including the first "active" report (base_status.py ~L315), before any
    sort. Legacy (orch_status_sync.py:200-231) only registers history by
    scanning the endpoint nonactive_dict buckets for a match, so it can
    never fire while the action is merely active. An ACTIVE action whose
    uuid equals last_dispatched_action_uuid must NOT emit
    RegisterHistoryEntry."""
    gsm = _gsm()
    act = _action([HloStatus.active])
    asm = _asm(act, "acquire", finished=False)
    _, cmds = fold_status(
        gsm,
        asm,
        loop_started=True,
        last_dispatched_action_uuid=act.action_uuid,
    )
    assert not any(isinstance(c, RegisterHistoryEntry) for c in cmds)


def test_newly_nonactive_go_to_live_buffer():
    """Checklist #3 needs two ingests: GlobalStatusModel only records a
    (uuid, status) pair in the "recently transitioned" list when the uuid is
    already present in gsm.active_dict at fold time (see
    GlobalStatusModel._sort_status, helao/core/models/server.py) -- i.e. the
    action must have been observed active on a prior fold before the fold
    that reports it finished. A single already-finished ingest (the
    original brief fixture) never populates gsm.active_dict in the first
    place, so nothing "newly" transitions and PushLiveBuffer is never
    emitted -- a fixture bug in the brief, fixed here to match the real
    model (drift, see status_fold.py module docstring)."""
    gsm = _gsm()
    act = _action([HloStatus.active])
    fold_status(
        gsm,
        _asm(act, "acquire", finished=False),
        loop_started=True,
        last_dispatched_action_uuid=None,
    )
    act.action_status = [HloStatus.finished]
    _, cmds = fold_status(
        gsm,
        _asm(act, "acquire", finished=True),
        loop_started=True,
        last_dispatched_action_uuid=None,
    )
    lb = [c for c in cmds if isinstance(c, PushLiveBuffer)]
    assert lb and act.action_uuid in dict(lb[0].items)  # checklist #3


def test_orch_state_derivation_idle_vs_busy():
    gsm = _gsm()
    active = _action([HloStatus.active])
    state, _ = fold_status(
        gsm,
        _asm(active, "acquire", finished=False),
        loop_started=True,
        last_dispatched_action_uuid=None,
    )
    assert state == OrchStatus.busy  # checklist #4
    done = _action([HloStatus.finished])
    gsm2 = _gsm()
    state2, _ = fold_status(
        gsm2,
        _asm(done, "acquire", finished=True),
        loop_started=True,
        last_dispatched_action_uuid=None,
    )
    assert state2 == OrchStatus.idle


def test_estopped_uuid_triggers_estop_only_when_loop_started():
    est = _action([HloStatus.finished, HloStatus.estopped])
    gsm_started = _gsm()
    # FIX: legacy's estop branch (orch_status_sync.py ~274-275) only calls
    # estop_loop() -- it never assigns orch.globalstatusmodel.orch_state.
    # Pin a pre-existing orch_state here and confirm fold_status leaves it
    # unchanged (no forced OrchStatus.estopped) on the estop branch.
    gsm_started.orch_state = OrchStatus.busy
    state_started, cmds_started = fold_status(
        gsm_started,
        _asm(est, "acquire", finished=True),
        loop_started=True,
        last_dispatched_action_uuid=None,
    )
    assert any(isinstance(c, TriggerEstopFromStatus) for c in cmds_started)
    assert state_started == OrchStatus.busy  # unchanged, matches legacy no-op
    _, cmds_stopped = fold_status(
        _gsm(),
        _asm(est, "acquire", finished=True),
        loop_started=False,
        last_dispatched_action_uuid=None,
    )
    assert not any(isinstance(c, TriggerEstopFromStatus) for c in cmds_stopped)


def test_errored_uuid_sets_error_state_when_started():
    err = _action([HloStatus.finished, HloStatus.errored])
    state, cmds = fold_status(
        _gsm(),
        _asm(err, "acquire", finished=True),
        loop_started=True,
        last_dispatched_action_uuid=None,
    )
    assert any(isinstance(c, SetOrchStateError) for c in cmds)
    assert state == OrchStatus.error


def test_identity_rule_foreign_orchestrator_not_folded_into_own_dicts():
    """Checklist #6 / MINOR-8: finished actions are mirrored into the
    orch-level dicts only when statusmodel.orchestrator == gsm.orchestrator."""
    gsm = _gsm()
    foreign = _action(
        [HloStatus.finished],
        orch=MachineModel(server_name="OTHER", machine_name="elsewhere"),
    )
    fold_status(
        gsm,
        _asm(foreign, "acquire", finished=True),
        loop_started=True,
        last_dispatched_action_uuid=None,
    )
    assert foreign.action_uuid not in gsm.nonactive_dict.get(HloStatus.finished, {})
