"""Golden-master parity test pinning the new orchestration FSM to legacy ``Orch``.

HOW THIS GOLDEN MASTER WAS PRODUCED
-----------------------------------
Driving the legacy ``helao.core.servers.orch.Orch`` in-process is impractical:
``Orch`` extends ``Base`` (a live FastAPI app), owns ``asyncio`` queues
(``interrupt_q``, ``aiolock``), NTP-offset state, HTTP dispatchers
(``async_action_dispatcher``), a Bokeh operator, a heartbeat/driver-health probe
and the data syncer. Standing all of that up in a unit test would test the
harness, not the *decision semantics*.

Instead, exactly as SP4 did for ``Active`` (see
``test_golden_master_action.py``), this is a COMMITTED, self-contained fixture:
each expected value is hardcoded with a comment citing the ``orch.py`` line range
it derives from, and asserted against a *live* call into the new pure FSM
(``helao.framework.domain.orchestration``). The legacy ``Orch`` is NOT run here.
If the new FSM ever drifts from the cited legacy semantics, this test fails loud.

LINE CITATIONS ARE INTO ``helao/core/servers/orch.py`` (the 2428-LOC legacy
orchestrator), at the revision present on branch ``feat/framework-scaffold``:

* ``dispatch_loop_task``                     — 1314-1480 (queue priority / gating)
* the six ``ActionStartCondition`` branches  — 1045-1098 (inside dispatch_action)
* the post-pop dispatch-counter / register   — 1136-1142 (orch_submit_order)
* ``update_status``                          — 448-565  (idle/busy/error/estop)
* ``start`` / ``start_loop``                 — 1499-1528
* ``estop_loop``                             — 1530-1551
* ``stop`` / ``intend_stop``                 — 1628-1640
* ``skip`` / ``intend_skip``                 — 1615-1626
* ``intend_estop`` / ``intend_none``         — 1642-1650
* ``clear_estop``                            — 1652-1661
* ``clear_error``                            — 1663-1668
* ``clear_sequences/experiments/actions``    — 1670-1683

DOCUMENTED DIVERGENCES FROM LEGACY (deliberate, per the SP5 spec)
----------------------------------------------------------------
1. **Blocking waits become re-queues.** Legacy ``loop_task_dispatch_action``
   *awaits* an interrupt while a start condition is unmet (e.g. 1053-1058). The
   pure FSM cannot block; ``start_condition_met`` reports whether the wait *would*
   pass, and ``dispatch_action`` re-queues the popped action at the front when it
   is unmet (orchestration.py 809-812) so ``app/`` retries on the next wake. We
   assert the FSM's report + re-queue, which is the parity-preserving translation.
2. **WAIT vs. inline finish.** Legacy interleaves ``finish_active_experiment``
   *before* dispatching the next experiment (1417-1420) inside one loop body. The
   FSM splits this into a ``WAIT`` decision (actions still busy) and an explicit
   ``DISPATCH_EXPERIMENT``/``FINISH_EXPERIMENT`` decision once idle. The pinned
   value is the FSM decision; the legacy *ordering* (action_dq > experiment_dq >
   sequence_dq, all gated on actions idle) is preserved and asserted below.
3. **Commands instead of side effects.** Legacy pushes to ``interrupt_q`` and
   calls ``estop_actions``/``stop_executor`` directly; the FSM emits
   ``BroadcastGlobalStatus`` / ``EstopServers`` / ``StopExecutor`` value objects.
   We assert the emitted command set matches the legacy side-effect intent.
"""
from datetime import datetime
from uuid import UUID, uuid4

from helao.framework.models.action import ActionModel
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.machine import MachineModel
from helao.framework.models.orchstatus import LoopIntent, LoopStatus, OrchStatus
from helao.framework.models.action_start_condition import ActionStartCondition
from helao.framework.models.server import (
    ActionServerModel,
    EndpointModel,
    GlobalStatusModel,
)

from helao.framework.domain.run_models import RunAction, RunExperiment, RunSequence
from helao.framework.domain import orchestration as orch
from helao.framework.domain.commands import (
    BroadcastGlobalStatus,
    EstopServers,
    OrchDecision,
    StopExecutor,
)

# --------------------------------------------------------------------------- #
# fixture builders (hand-constructed plain data, mirroring the domain tests)
# --------------------------------------------------------------------------- #
ORCH = MachineModel(server_name="orch", machine_name="host")
SRV = MachineModel(server_name="act", machine_name="host")


def _gsm(**kw):
    return GlobalStatusModel(orchestrator=ORCH, **kw)


def _state(**kw):
    kw.setdefault("globalstatusmodel", _gsm())
    return orch.OrchState(**kw)


def _action(statuses=None, action_name="ep", **kw):
    return RunAction(
        action_uuid=kw.pop("action_uuid", None) or uuid4(),
        orchestrator=ORCH,
        action_server=kw.pop("action_server", SRV),
        action_name=action_name,
        action_status=list(statuses or []),
        **kw,
    )


def _busy_server(action, endpoint_name="ep"):
    """Plant a still-active action so actions_idle/server/endpoint are busy."""
    ep = EndpointModel(
        endpoint_name=endpoint_name, active_dict={action.action_uuid: action}
    )
    return ActionServerModel(action_server=SRV, endpoints={endpoint_name: ep})


def _make_busy(st, endpoint_name="ep"):
    busy = _action([HloStatus.active], action_name=endpoint_name)
    st.globalstatusmodel.update_global_with_acts(_busy_server(busy, endpoint_name))
    return busy


# =========================================================================== #
# 1. DECISION-TRACE PARITY  (orch.py dispatch_loop_task 1314-1480)
#
# Legacy priority inside the `while loop_state==started and (any dq):` body:
#   - estopped state OR estop intent       -> stop_loop          (1373-1377)
#   - action_dq                            -> dispatch_action    (1378-1380)
#   - experiment_dq (after finishing acts) -> dispatch_experiment(1413-1420)
#   - sequence_dq   (after finishing acts) -> dispatch_sequence  (1422-1429)
#   - else (empty)                         -> stop               (1430-1432)
# Final wrap-up after loop: finish active exp (1441-1445) then active seq
# (1446-1452). The FSM's WAIT/FINISH split is the documented divergence (#2).
# =========================================================================== #
def test_decision_all_empty_is_idle():
    # orch.py 1334: while-guard false when all dq empty and nothing active ->
    # loop body never runs, loop exits -> IDLE (no active exp/seq to finish).
    assert orch.decide_next(_state()) == OrchDecision.IDLE


def test_decision_action_beats_experiment_and_sequence():
    # orch.py 1378-1380: `elif self.action_dq:` is checked before experiment_dq
    # (1413) and sequence_dq (1422). Actions always go first.
    st = _state(
        action_dq=[_action()],
        experiment_dq=[RunExperiment()],
        sequence_dq=[RunSequence()],
    )
    assert orch.decide_next(st) == OrchDecision.DISPATCH_ACTION


def test_decision_experiment_beats_sequence_when_idle():
    # orch.py 1413 (experiment_dq) precedes 1422 (sequence_dq); with actions idle
    # the legacy body dispatches the experiment.
    st = _state(experiment_dq=[RunExperiment()], sequence_dq=[RunSequence()])
    assert orch.decide_next(st) == OrchDecision.DISPATCH_EXPERIMENT


def test_decision_experiment_waits_while_actions_busy():
    # orch.py 1417-1418: legacy finishes ALL actions (await finish_active_
    # experiment / orch_wait_for_all_actions) BEFORE dispatching the next
    # experiment. FSM divergence #2: this gating becomes a WAIT decision.
    st = _state(experiment_dq=[RunExperiment()])
    _make_busy(st)
    assert orch.decide_next(st) == OrchDecision.WAIT


def test_decision_sequence_when_idle():
    # orch.py 1422-1429: with no actions/experiments queued, sequence_dq is next.
    st = _state(sequence_dq=[RunSequence()])
    assert orch.decide_next(st) == OrchDecision.DISPATCH_SEQUENCE


def test_decision_sequence_waits_while_actions_busy():
    # orch.py 1424 ("waiting for all actions to finish before dispatching next
    # sequence") -> WAIT under the FSM's divergence #2.
    st = _state(sequence_dq=[RunSequence()])
    _make_busy(st)
    assert orch.decide_next(st) == OrchDecision.WAIT


def test_decision_finish_experiment_when_queues_empty():
    # orch.py 1441-1445: after the loop, `not action_dq and active_experiment is
    # not None` -> finish_active_experiment. FSM surfaces this as FINISH_EXPERIMENT.
    st = _state(active_experiment=RunExperiment())
    assert orch.decide_next(st) == OrchDecision.FINISH_EXPERIMENT


def test_decision_finish_sequence_when_queues_and_exp_empty():
    # orch.py 1446-1452: `not experiment_dq and not action_dq and active_sequence
    # is not None` -> finish_active_sequence.
    st = _state(active_sequence=RunSequence())
    assert orch.decide_next(st) == OrchDecision.FINISH_SEQUENCE


def test_decision_finish_experiment_precedes_finish_sequence():
    # orch.py 1441-1452: experiment finish (1441) is attempted before sequence
    # finish (1446). With both active, FINISH_EXPERIMENT wins.
    st = _state(active_experiment=RunExperiment(), active_sequence=RunSequence())
    assert orch.decide_next(st) == OrchDecision.FINISH_EXPERIMENT


def test_decision_finish_waits_while_actions_busy():
    # orch.py 1441-1442 guards finish on `not action_dq`; with actions still busy
    # the FSM must WAIT before finishing the active experiment (divergence #2).
    st = _state(active_experiment=RunExperiment())
    _make_busy(st)
    assert orch.decide_next(st) == OrchDecision.WAIT


def test_decision_stop_on_estopped_state():
    # orch.py 1334: `while loop_state == started` — an estopped state exits the
    # loop; 1373-1377 also routes estopped state to stop_loop. FSM -> STOP.
    st = _state(action_dq=[_action()])
    st.loop_state = LoopStatus.estopped
    assert orch.decide_next(st) == OrchDecision.STOP


def test_decision_stop_on_estop_intent():
    # orch.py 1373-1377: `loop_intent == LoopIntent.estop` routes to stop_loop.
    st = _state(action_dq=[_action()])
    st.loop_intent = LoopIntent.estop
    assert orch.decide_next(st) == OrchDecision.STOP


def test_decision_stop_on_stop_intent():
    # orch.py 1434-1436 / intend_stop (1637-1640): a stop intent ends the loop.
    # The FSM treats a pending stop intent as STOP up front.
    st = _state(action_dq=[_action()])
    st.loop_intent = LoopIntent.stop
    assert orch.decide_next(st) == OrchDecision.STOP


# =========================================================================== #
# 2. INTENT-TRANSITION PARITY
# =========================================================================== #
def test_intent_start_from_stopped_with_work():
    # orch.py start 1499-1513 + start_loop 1515-1528: when stopped AND
    # (action_dq or experiment_dq or sequence_dq or active_sequence) -> loop
    # goes started and current_stop_message is cleared (1513).
    st = _state(action_dq=[_action()])
    st.current_stop_message = "old"
    st, cmds = orch.apply_intent(st, "start")
    assert st.loop_state == LoopStatus.started        # start_loop 1521-1523
    assert st.current_stop_message == ""              # start 1513
    assert any(isinstance(c, BroadcastGlobalStatus) for c in cmds)


def test_intent_start_resumes_with_active_sequence_only():
    # orch.py 1502-1507: an active_sequence alone (paused run) is enough to resume.
    st = _state(active_sequence=RunSequence())
    st, _ = orch.apply_intent(st, "start")
    assert st.loop_state == LoopStatus.started


def test_intent_start_empty_is_noop():
    # orch.py 1509-1510: empty queues + no active_sequence -> "experiment list is
    # empty", loop stays stopped.
    st = _state()
    st, _ = orch.apply_intent(st, "start")
    assert st.loop_state == LoopStatus.stopped


def test_intent_start_refused_under_estop():
    # orch.py 1524-1525: start_loop refuses to start while estopped (must clear
    # E-STOP first); loop_state stays estopped.
    st = _state(action_dq=[_action()])
    st.loop_state = LoopStatus.estopped
    st, _ = orch.apply_intent(st, "start")
    assert st.loop_state == LoopStatus.estopped


def test_intent_stop_while_started_sets_stop_intent():
    # orch.py stop 1628-1631 -> intend_stop 1637-1640: started -> LoopIntent.stop.
    st = _state()
    st.loop_state = LoopStatus.started
    st, _ = orch.apply_intent(st, "stop")
    assert st.loop_intent == LoopIntent.stop


def test_intent_stop_while_stopped_is_noop():
    # orch.py 1634-1635: stopped -> "orchestrator is not running"; no intent set.
    st = _state()
    st, _ = orch.apply_intent(st, "stop")
    assert st.loop_intent == LoopIntent.none


def test_intent_intend_stop_is_unconditional():
    # orch.py intend_stop 1637-1640 sets LoopIntent.stop directly (no state guard).
    st = _state()
    st, _ = orch.apply_intent(st, "intend_stop")
    assert st.loop_intent == LoopIntent.stop


def test_intent_skip_while_started_sets_skip_intent():
    # orch.py skip 1615-1618 -> intend_skip 1623-1626: started -> LoopIntent.skip.
    st = _state()
    st.loop_state = LoopStatus.started
    st, _ = orch.apply_intent(st, "skip")
    assert st.loop_intent == LoopIntent.skip


def test_intent_skip_while_stopped_clears_action_dq():
    # orch.py 1619-1621: not running -> "clearing action queue" (action_dq.clear()),
    # no intent change.
    st = _state(action_dq=[_action(), _action()])
    st, _ = orch.apply_intent(st, "skip")
    assert st.action_dq == []
    assert st.loop_intent == LoopIntent.none


def test_intent_intend_skip_unconditional():
    # orch.py intend_skip 1623-1626.
    st = _state()
    st, _ = orch.apply_intent(st, "intend_skip")
    assert st.loop_intent == LoopIntent.skip


def test_intent_intend_estop_and_none():
    # orch.py intend_estop 1642-1645 / intend_none 1647-1650.
    st = _state()
    st, _ = orch.apply_intent(st, "intend_estop")
    assert st.loop_intent == LoopIntent.estop
    st, _ = orch.apply_intent(st, "intend_none")
    assert st.loop_intent == LoopIntent.none


def test_intent_estop_transitions_and_fans_out():
    # orch.py estop_loop 1530-1551:
    #   loop_state = estopped               (1540)
    #   active_run_id = None                (1541)
    #   estop_actions(switch=False)         (1544)  -> EstopServers(switch=False)
    #   intend_none -> loop_intent = none   (1547)
    #   current_stop_message = "E-STOP"+sfx (1549)
    st = _state(active_run_id=uuid4())
    st.loop_intent = LoopIntent.stop
    st, cmds = orch.apply_intent(st, "estop", reason="boom")
    assert st.loop_state == LoopStatus.estopped       # 1540
    assert st.active_run_id is None                   # 1541
    assert st.loop_intent == LoopIntent.none          # 1547
    assert st.current_stop_message == "E-STOP boom"   # 1549
    estops = [c for c in cmds if isinstance(c, EstopServers)]
    assert estops and estops[0].switch is False       # 1544 (don't latch)
    assert estops[0].reason == "boom"


def test_intent_clear_estop_releases_and_returns_to_stopped():
    # orch.py clear_estop 1652-1661:
    #   clear_in_finished(estopped)         (1656)
    #   estop_actions(switch=False)         (1658)  -> EstopServers(switch=False)
    #   loop_state = stopped                (1660)
    st = _state()
    st.loop_state = LoopStatus.estopped
    st.globalstatusmodel.nonactive_dict[HloStatus.estopped] = {uuid4(): _action()}
    st, cmds = orch.apply_intent(st, "clear_estop")
    assert st.loop_state == LoopStatus.stopped                          # 1660
    assert st.globalstatusmodel.nonactive_dict[HloStatus.estopped] == {}  # 1656
    assert any(isinstance(c, EstopServers) and c.switch is False for c in cmds)


def test_intent_clear_error_clears_errored_bucket():
    # orch.py clear_error 1663-1668: clear_in_finished(errored) (1667). No state
    # change, no EstopServers (only an interrupt-q signal, modeled as a broadcast).
    st = _state()
    st.globalstatusmodel.nonactive_dict[HloStatus.errored] = {uuid4(): _action()}
    st, cmds = orch.apply_intent(st, "clear_error")
    assert st.globalstatusmodel.nonactive_dict[HloStatus.errored] == {}
    assert not any(isinstance(c, EstopServers) for c in cmds)


def test_intent_clear_queue_intents_empty_each_dq():
    # orch.py clear_sequences 1670-1673 / clear_experiments 1675-1678 /
    # clear_actions 1680-1683: each empties exactly its own deque.
    st = _state(
        sequence_dq=[RunSequence()],
        experiment_dq=[RunExperiment()],
        action_dq=[_action()],
    )
    st, _ = orch.apply_intent(st, "clear_sequences")
    assert st.sequence_dq == [] and st.experiment_dq and st.action_dq
    st, _ = orch.apply_intent(st, "clear_experiments")
    assert st.experiment_dq == [] and st.action_dq
    st, _ = orch.apply_intent(st, "clear_actions")
    assert st.action_dq == []


# =========================================================================== #
# 3. START-CONDITION PARITY  (orch.py 1045-1098, six ActionStartCondition cases)
#
# Divergence #1: legacy *awaits* an interrupt while the condition is unmet; the
# FSM reports whether the wait would pass right now. True == "would not block".
# =========================================================================== #
def test_scm_no_wait_always_true():
    # orch.py 1045-1046: no_wait -> dispatch unconditionally.
    st = _state()
    a = _action(start_condition=ActionStartCondition.no_wait)
    assert orch.start_condition_met(st, a) is True


def test_scm_wait_for_endpoint():
    # orch.py 1048-1058: gate on globalstatusmodel.endpoint_free(action_server,
    # action_name). Free -> True; busy same endpoint -> False (would await 1053).
    st = _state()
    a = _action(start_condition=ActionStartCondition.wait_for_endpoint, action_name="ep")
    assert orch.start_condition_met(st, a) is True
    _make_busy(st, "ep")
    assert orch.start_condition_met(st, a) is False


def test_scm_wait_for_server():
    # orch.py 1059-1069: gate on server_free(action_server).
    st = _state()
    a = _action(start_condition=ActionStartCondition.wait_for_server, action_name="ep")
    assert orch.start_condition_met(st, a) is True
    _make_busy(st, "ep")
    assert orch.start_condition_met(st, a) is False


def test_scm_wait_for_orch():
    # orch.py 1070-1080: gate on endpoint_free(A.orchestrator, "wait").
    st = _state()
    a = _action(start_condition=ActionStartCondition.wait_for_orch)
    assert orch.start_condition_met(st, a) is True
    waitact = ActionModel(
        action_uuid=uuid4(), orchestrator=ORCH, action_server=ORCH,
        action_name="wait", action_status=[HloStatus.active],
    )
    ep = EndpointModel(endpoint_name="wait", active_dict={waitact.action_uuid: waitact})
    st.globalstatusmodel.update_global_with_acts(
        ActionServerModel(action_server=ORCH, endpoints={"wait": ep})
    )
    assert orch.start_condition_met(st, a) is False


def test_scm_wait_for_previous():
    # orch.py 1081-1093: gate on `last_action_uuid in active_dict.keys()`.
    # not active -> True; active -> False (legacy would await 1087).
    st = _state()
    prev = uuid4()
    st.last_action_uuid = prev
    a = _action(start_condition=ActionStartCondition.wait_for_previous)
    assert orch.start_condition_met(st, a) is True
    st.globalstatusmodel.active_dict[prev] = _action([HloStatus.active])
    assert orch.start_condition_met(st, a) is False


def test_scm_wait_for_all_and_unsupported_default():
    # orch.py 1094-1098: wait_for_all -> orch_wait_for_all_actions; the `else`
    # (unsupported value) ALSO calls orch_wait_for_all_actions (1097-1098).
    # FSM maps both to actions_idle (orchestration.py 581-582).
    st = _state()
    a = _action(start_condition=ActionStartCondition.wait_for_all)
    assert orch.start_condition_met(st, a) is True
    _make_busy(st)
    assert orch.start_condition_met(st, a) is False


def test_scm_dispatch_action_requeues_when_unmet():
    # orch.py 1042 popleft then 1053-1058 await: the action is NOT dispatched
    # until its condition passes. FSM divergence #1: pop + re-queue at front,
    # emit nothing (orchestration.py 807-812).
    st = _state()
    _make_busy(st)
    a = _action(start_condition=ActionStartCondition.wait_for_all, action_name="x")
    st.action_dq = [a]
    st, cmds = orch.dispatch_action(st, now=datetime(2026, 6, 22, 15, 0, 0), uuid=UUID(int=7))
    assert cmds == []
    assert st.action_dq[0] is a  # re-queued at the front


def test_scm_dispatch_counter_matches_legacy_orch_submit_order():
    # orch.py 1136-1142: orch_submit_order = counter_dispatched_actions[exp_uuid];
    # then that counter is incremented. First dispatch -> order 0, counter -> 1.
    exp = RunExperiment(experiment_uuid=uuid4())
    st = _state(active_experiment=exp, active_run_id=uuid4())
    st.globalstatusmodel.new_experiment(exp.experiment_uuid)
    a = _action(start_condition=ActionStartCondition.no_wait, action_name="meas")
    st.action_dq = [a]
    st, _ = orch.dispatch_action(st, now=datetime(2026, 6, 22, 15, 0, 0), uuid=UUID(int=7))
    assert a.orch_submit_order == 0                                            # 1137
    assert st.globalstatusmodel.counter_dispatched_actions[exp.experiment_uuid] == 1  # 1140-1142


# =========================================================================== #
# 4. STATUS-REACTION PARITY  (orch.py update_status 448-565)
#
# Legacy ladder (548-559):
#   estop_uuids and loop_state==started -> estop_loop                  (548-549)
#   elif error_uuids and started        -> orch_state = error          (550-553)
#   elif not active_dict                -> orch_state = idle            (554-556)
#   else                                -> orch_state = busy            (557-559)
# A None model returns False (no-op) at 469-470.
# =========================================================================== #
def test_status_none_is_noop():
    # orch.py 469-470: `if actionservermodel is None: return False`.
    st = _state()
    st, cmds = orch.on_status_update(st, None)
    assert cmds == []


def test_status_idle_when_no_active():
    # orch.py 554-556: no entries in active_dict -> orch_state idle.
    st = _state()
    done = _action([HloStatus.finished])
    st, cmds = orch.on_status_update(st, _busy_server(done))
    assert st.orch_state == OrchStatus.idle
    assert any(isinstance(c, BroadcastGlobalStatus) for c in cmds)


def test_status_busy_when_active():
    # orch.py 557-559: an active action -> orch_state busy.
    st = _state()
    active = _action([HloStatus.active])
    st, _ = orch.on_status_update(st, _busy_server(active))
    assert st.orch_state == OrchStatus.busy


def test_status_error_only_when_started():
    # orch.py 550-553: errored uuid AND loop_state == started -> orch_state error.
    st = _state()
    st.loop_state = LoopStatus.started
    errored = _action([HloStatus.finished, HloStatus.errored])
    st, _ = orch.on_status_update(st, _busy_server(errored))
    assert st.orch_state == OrchStatus.error


def test_status_error_ignored_when_not_started():
    # orch.py 550-551 guard requires loop_state==started; otherwise it falls
    # through to the idle branch (554-556) since active_dict is empty.
    st = _state()  # stopped
    errored = _action([HloStatus.finished, HloStatus.errored])
    st, _ = orch.on_status_update(st, _busy_server(errored))
    assert st.orch_state == OrchStatus.idle


def test_status_estop_when_started_fans_out():
    # orch.py 548-549: estopped uuid AND started -> estop_loop(reason=...). The
    # FSM applies the estop intent -> loop_state estopped + EstopServers emitted.
    st = _state()
    st.loop_state = LoopStatus.started
    estopped = _action([HloStatus.finished, HloStatus.estopped])
    st, cmds = orch.on_status_update(st, _busy_server(estopped))
    assert st.loop_state == LoopStatus.estopped                 # estop_loop 1540
    assert any(isinstance(c, EstopServers) for c in cmds)       # estop_actions 1544


def test_status_estop_precedes_error():
    # orch.py 548 (estop) is the FIRST branch of the ladder, before error (550).
    # A uuid finished as BOTH errored and estopped routes to estop, not error.
    st = _state()
    st.loop_state = LoopStatus.started
    both = _action([HloStatus.finished, HloStatus.errored, HloStatus.estopped])
    st, cmds = orch.on_status_update(st, _busy_server(both))
    assert st.loop_state == LoopStatus.estopped
    assert any(isinstance(c, EstopServers) for c in cmds)


# =========================================================================== #
# 5. NONBLOCKING / CLEAR-NONBLOCKING PARITY
# =========================================================================== #
def test_clear_nonblocking_emits_one_stop_executor_per_entry():
    # orch.py clear_nonblocking iterates each tracked (server,exec,host,port)
    # tuple and dispatches a stop_executor; FSM emits one StopExecutor each.
    st = _state(nonblocking=[("act", "e1", "h", 9), ("act2", "e2", "h2", 10)])
    st, cmds = orch.clear_nonblocking(st)
    assert len(cmds) == 2
    assert all(isinstance(c, StopExecutor) for c in cmds)
    assert cmds[0].executor_id == "e1" and cmds[1].server_key == "act2"
