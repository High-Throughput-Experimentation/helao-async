"""Clear E-stop / clear error must not be undone by the next status fold.

``GlobalStatusModel.clear_in_finished`` emptied only the orchestrator's own
``nonactive_dict`` bucket. Each action server's last endpoint status also sits
in ``server_dict[...].endpoints[...].nonactive_dict``, and every later
``update_status`` (from ANY server or endpoint) re-runs ``_sort_status`` over
all of them, which put the cleared uuid straight back. With the loop
``started`` ingestion then re-E-STOPped on the stale uuid, so Start after
Clear E-stop immediately E-STOPped again.
"""

from uuid import uuid4

import pytest

from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.orchstatus import LoopStatus
from helao.core.models.server import (
    ActionServerModel,
    EndpointModel,
    GlobalStatusModel,
)
from helao.helpers.premodels import Action
from helao.hexagon.domain.orchestration import (
    ErroredUuidIngested,
    EstoppedUuidIngested,
    StatusChanged,
)
from helao.hexagon.tests.test_ingestion import ORCH_M, _act, _asm, _make

ORCH = MachineModel(server_name="ORCH", machine_name="h")
SIM = MachineModel(server_name="SIM", machine_name="h")


def _act_on(server, name, statuses, uuid=None, orch=ORCH):
    a = Action(action_name=name, action_server=server, orchestrator=orch)
    a.action_status = list(statuses)
    a.action_uuid = uuid or uuid4()
    return a


def _fold(gsm, server, name, act):
    ep = EndpointModel(endpoint_name=name)
    ep.active_dict = {act.action_uuid: act}
    return gsm.update_global_with_acts(
        ActionServerModel(action_server=server, endpoints={name: ep})
    )


@pytest.mark.parametrize(
    "status", [HloStatus.estopped, HloStatus.errored], ids=["estopped", "errored"]
)
def test_cleared_uuid_is_not_resurrected_by_another_servers_status(status):
    gsm = GlobalStatusModel(orchestrator=ORCH)
    running = _act_on(SIM, "acquire_data", [HloStatus.active])
    _fold(gsm, SIM, "acquire_data", running)
    ended = _act_on(
        SIM, "acquire_data", [status, HloStatus.finished], running.action_uuid
    )
    _fold(gsm, SIM, "acquire_data", ended)
    assert gsm.find_hlostatus_in_finished(status), "setup: never recorded"

    gsm.clear_in_finished(hlostatus=status)
    assert not gsm.find_hlostatus_in_finished(status)

    # the next run: ORCH's own `wait` goes active, a different endpoint
    _fold(gsm, ORCH, "wait", _act_on(ORCH, "wait", [HloStatus.active]))
    assert not gsm.find_hlostatus_in_finished(status)


@pytest.mark.asyncio
async def test_ingestion_does_not_restop_on_a_cleared_estopped_uuid():
    orch, spy, ing = _make()
    gsm = orch.globalstatusmodel
    u = uuid4()
    est = _act(u, [HloStatus.active, HloStatus.finished, HloStatus.estopped])
    await ing.update_status(actionservermodel=_asm(est, active=False))
    gsm.clear_in_finished(hlostatus=HloStatus.estopped)
    gsm.loop_state = LoopStatus.started  # operator pressed Start
    spy.events.clear()
    # first status after Start: another endpoint going active
    other = ActionServerModel(
        action_server=ORCH_M,
        endpoints={"wait": EndpointModel(endpoint_name="wait")},
    )
    w = _act_on(ORCH_M, "wait", [HloStatus.active], orch=ORCH_M)
    other.endpoints["wait"].active_dict = {w.action_uuid: w}  # type: ignore[dict-item]
    await ing.update_status(actionservermodel=other)
    assert spy.events == [StatusChanged(any_active=True)], spy.events


@pytest.mark.asyncio
async def test_ingestion_does_not_reerror_on_a_cleared_errored_uuid():
    orch, spy, ing = _make()
    gsm = orch.globalstatusmodel
    err = _act(uuid4(), [HloStatus.active, HloStatus.finished, HloStatus.errored])
    await ing.update_status(actionservermodel=_asm(err, active=False))
    gsm.clear_in_finished(hlostatus=HloStatus.errored)
    gsm.loop_state = LoopStatus.started
    spy.events.clear()
    w = _act_on(ORCH_M, "wait", [HloStatus.active], orch=ORCH_M)
    other = ActionServerModel(
        action_server=ORCH_M, endpoints={"wait": EndpointModel(endpoint_name="wait")}
    )
    other.endpoints["wait"].active_dict = {w.action_uuid: w}  # type: ignore[dict-item]
    await ing.update_status(actionservermodel=other)
    assert spy.events == [StatusChanged(any_active=True)], spy.events


@pytest.mark.asyncio
async def test_a_new_estopped_uuid_after_the_clear_still_restops():
    orch, spy, ing = _make()
    gsm = orch.globalstatusmodel
    old = _act(uuid4(), [HloStatus.active, HloStatus.finished, HloStatus.estopped])
    await ing.update_status(actionservermodel=_asm(old, active=False))
    gsm.clear_in_finished(hlostatus=HloStatus.estopped)
    gsm.loop_state = LoopStatus.started
    spy.events.clear()
    new_u = uuid4()
    new = _act(new_u, [HloStatus.active, HloStatus.finished, HloStatus.estopped])
    await ing.update_status(actionservermodel=_asm(new, active=False))
    assert len(spy.events) == 1 and isinstance(spy.events[0], EstoppedUuidIngested)
    assert str(new_u) in spy.events[0].reason
    assert str(old.action_uuid) not in spy.events[0].reason


def test_drop_estopped_keeps_unrelated_finished_actions():
    gsm = GlobalStatusModel(orchestrator=ORCH)
    ok = _act_on(SIM, "other", [HloStatus.active, HloStatus.finished])
    _fold(gsm, SIM, "other", ok)
    bad = _act_on(SIM, "acquire_data", [HloStatus.estopped, HloStatus.finished])
    _fold(gsm, SIM, "acquire_data", bad)
    assert gsm.drop_estopped_in_finished() == {bad.action_uuid}
    assert gsm.drop_estopped_in_finished() == set()
    _fold(gsm, ORCH, "wait", _act_on(ORCH, "wait", [HloStatus.active]))
    assert not gsm.find_hlostatus_in_finished(HloStatus.estopped)
    assert ok.action_uuid in gsm.nonactive_dict[HloStatus.finished]
