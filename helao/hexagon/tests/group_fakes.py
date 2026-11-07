"""Read-only fakes shaped like OrchHost, for the /ws_orch snapshot and feed tests.

Every fake act/exp/seq attribute must be a field of the real model, pinned by
``test_fakes_use_real_model_field_names`` in test_group_snapshot.py.
"""

from collections import deque
from datetime import datetime
from typing import Optional
from types import SimpleNamespace
from uuid import uuid4

from helao.core.models.hlostatus import HloStatus
from helao.core.models.orchstatus import LoopIntent, LoopStatus, OrchStatus

T0 = datetime(2026, 11, 6, 10, 0, 0)


class NoScan(dict):
    """A bucket that may be looked up and measured but never iterated.

    Pins "per-tick work does not grow with the finished actions": a read that
    walks the bucket raises. ``keys()`` is a view and is not overridden, so a
    test that needs a walk to fail must not rely on it.
    """

    armed = True

    def _no(self, *a, **k):
        if self.armed:
            raise AssertionError("bucket iterated")

    def __iter__(self):
        self._no()
        return super().__iter__()

    def items(self):
        self._no()
        return super().items()

    def values(self):
        self._no()
        return super().values()

    def keys(self):
        self._no()
        return super().keys()


def fake_act(
    server="SIM",
    name="acquire",
    exp_uuid=None,
    ts: Optional[datetime] = T0,
    fin: Optional[datetime] = None,
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


def fake_exp(
    name="exp",
    with_uuid=True,
    ts: Optional[datetime] = None,
    fin: Optional[datetime] = None,
    status=(),
):
    return SimpleNamespace(
        experiment_uuid=uuid4() if with_uuid else None,
        experiment_name=name,
        experiment_timestamp=ts,
        experiment_finished_timestamp=fin,
        experiment_status=list(status),
        dispatched_actions=[],
    )


def fake_seq(name="seq", ts: Optional[datetime] = T0):
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
        parked_head_action=None,
    )
