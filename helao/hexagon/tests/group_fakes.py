"""Read-only fakes shaped like OrchHost, for the /ws_orch snapshot and feed tests.

Attribute names are pinned against the real models by
``test_fakes_use_real_model_field_names`` in test_group_snapshot.py.
"""

from collections import deque
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from helao.core.models.hlostatus import HloStatus
from helao.core.models.orchstatus import LoopIntent, LoopStatus, OrchStatus

T0 = datetime(2026, 11, 6, 10, 0, 0)


def fake_act(
    server="SIM",
    name="acquire",
    exp_uuid=None,
    ts=T0,
    fin=None,
    status=(HloStatus.active,),
):
    return SimpleNamespace(
        action_uuid=uuid4(),
        action_name=name,
        action_server=SimpleNamespace(server_name=server),
        experiment_uuid=exp_uuid,
        action_timestamp=ts,
        action_finished_timestamp=fin,
        action_status=list(status),
    )


def fake_exp(name="exp", with_uuid=True, ts=None, fin=None, status=()):
    return SimpleNamespace(
        experiment_uuid=uuid4() if with_uuid else None,
        experiment_name=name,
        experiment_timestamp=ts,
        experiment_finished_timestamp=fin,
        experiment_status=list(status),
        dispatched_actions=[],
    )


def fake_seq(name="seq", ts=T0):
    return SimpleNamespace(
        sequence_uuid=uuid4(),
        sequence_name=name,
        sequence_label="label",
        sequence_timestamp=ts,
        dispatched_experiments=[],
    )


def fake_orch(servers=("SIM", "PSTAT")):
    gsm = SimpleNamespace(
        loop_state=LoopStatus.stopped,
        loop_intent=LoopIntent.none,
        orch_state=OrchStatus.idle,
        server_dict={},
        active_dict={},
        nonactive_dict={},
        counter_dispatched_actions={},
    )
    world = {
        "servers": {
            "ORCH": {"group": "orchestrator"},
            **{key: {"group": "action"} for key in servers},
            "UI": {"group": "visualizer"},
        }
    }
    return SimpleNamespace(
        server_key="ORCH",
        world_cfg=world,
        globalstatusmodel=gsm,
        status_summary={},
        active_sequence=None,
        active_experiment=None,
        sequence_dq=deque(),
        experiment_dq=deque(),
        action_dq=deque(),
    )
