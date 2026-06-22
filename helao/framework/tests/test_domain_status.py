"""Tests for the pure global-status facade ``helao.framework.domain.status``.

Builds hand-constructed `GlobalStatusModel` / `ActionServerModel` /
`EndpointModel` fixtures (mirroring ``test_models_server.py``) and verifies the
facade delegates correctly and projects the model's ``(uuid, status_name)``
tuples down to plain UUID lists.
"""
from uuid import uuid4

from helao.framework.models.action import ActionModel
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.machine import MachineModel
from helao.framework.models.server import (
    ActionServerModel,
    EndpointModel,
    GlobalStatusModel,
)
from helao.framework.domain import status


ORCH = MachineModel(server_name="orch", machine_name="host")
SRV = MachineModel(server_name="act", machine_name="host")


def _action(statuses, exp_uuid=None, action_uuid=None):
    return ActionModel(
        action_uuid=action_uuid or uuid4(),
        experiment_uuid=exp_uuid,
        orchestrator=ORCH,
        action_status=list(statuses),
    )


def _server_model(action, endpoint_name="ep"):
    ep = EndpointModel(
        endpoint_name=endpoint_name, active_dict={action.action_uuid: action}
    )
    return ActionServerModel(action_server=SRV, endpoints={endpoint_name: ep})


# --------------------------------------------------------------------------- #
# actions_idle / server_free / endpoint_free
# --------------------------------------------------------------------------- #
def test_idle_and_free_on_empty_model():
    gsm = GlobalStatusModel(orchestrator=ORCH)
    assert status.actions_idle(gsm) is True
    assert status.server_free(gsm, SRV) is True
    assert status.endpoint_free(gsm, SRV, "ep") is True


def test_idle_and_free_with_active_action():
    gsm = GlobalStatusModel(orchestrator=ORCH)
    active = _action([HloStatus.active])
    gsm.update_global_with_acts(_server_model(active))
    assert status.actions_idle(gsm) is False
    assert status.server_free(gsm, SRV) is False
    assert status.endpoint_free(gsm, SRV, "ep") is False
    # a different endpoint on the same server is still free
    assert status.endpoint_free(gsm, SRV, "other") is True


def test_free_is_true_after_action_finishes():
    gsm = GlobalStatusModel(orchestrator=ORCH)
    done = _action([HloStatus.finished])
    gsm.update_global_with_acts(_server_model(done))
    assert status.actions_idle(gsm) is True
    assert status.server_free(gsm, SRV) is True
    assert status.endpoint_free(gsm, SRV, "ep") is True


# --------------------------------------------------------------------------- #
# merge_server_status / newly_finished
# --------------------------------------------------------------------------- #
def test_newly_finished_returns_uuid_list_on_completion():
    gsm = GlobalStatusModel(orchestrator=ORCH)
    active = _action([HloStatus.active])
    asm = _server_model(active)
    # first merge while active: nothing finishes
    assert status.newly_finished(gsm, asm) == []

    # action now reports finished on the next snapshot
    active.action_status = [HloStatus.finished]
    finished = status.newly_finished(gsm, asm)
    assert finished == [active.action_uuid]
    # result is a plain list of UUIDs, not (uuid, status) tuples
    assert all(isinstance(u, type(active.action_uuid)) for u in finished)


def test_merge_server_status_matches_newly_finished_and_mutates_gsm():
    gsm = GlobalStatusModel(orchestrator=ORCH)
    act = _action([HloStatus.active])
    asm = _server_model(act)
    # first merge registers it as active (not newly-finished)
    assert status.merge_server_status(gsm, asm) == []
    # side effect: snapshot folded into gsm
    assert SRV.as_key() in gsm.server_dict

    # next snapshot reports finished -> the active->finished transition is
    # what the model (and facade) report as newly-finished.
    act.action_status = [HloStatus.finished]
    out = status.merge_server_status(gsm, asm)
    assert out == [act.action_uuid]
    assert act.action_uuid in gsm.nonactive_dict[HloStatus.finished]


def test_merge_server_status_empty_when_nothing_finished():
    gsm = GlobalStatusModel(orchestrator=ORCH)
    active = _action([HloStatus.active])
    assert status.merge_server_status(gsm, _server_model(active)) == []
