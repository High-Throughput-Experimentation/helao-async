"""Tests for the ported Executor four-phase contract (domain/executor.py).

The :class:`Executor` is a pure abstraction (no I/O): driver authors subclass it
and implement ``_pre_exec``/``_exec``/``_poll``/``_post_exec``/``_manual_stop``,
or bind callables at runtime via the ``set_*`` binders. These tests pin the
phase signatures, default return shapes, attributes, and the runtime binders.
"""

import asyncio

import pytest

from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.domain.executor import Executor


class _FakeAction:
    def __init__(self, name="dummy_act", uuid="abc", params=None):
        self.action_name = name
        self.action_uuid = uuid
        self.action_params = params if params is not None else {}


class _FakeActive:
    """Minimal stand-in for the action wrapper the Executor stamps exec_id onto."""

    def __init__(self, action=None):
        self.action = action if action is not None else _FakeAction()


def _make(**kwargs):
    return Executor(active=_FakeActive(), **kwargs)


def test_default_attributes():
    ex = _make()
    assert ex.oneoff is True
    assert ex.poll_rate == 0.2
    assert ex.concurrent is True
    assert ex.duration == -1  # no "duration" in action_params
    assert ex.exec_id == "dummy_act abc"
    assert isinstance(ex.start_time, float)


def test_attributes_overridable():
    ex = _make(poll_rate=1.5, oneoff=False, concurrent=False, exec_id="X")
    assert ex.oneoff is False
    assert ex.poll_rate == 1.5
    assert ex.concurrent is False
    assert ex.exec_id == "X"


def test_exec_id_stamped_on_action():
    active = _FakeActive()
    ex = Executor(active=active)
    assert active.action.exec_id == ex.exec_id


def test_duration_pulled_from_action_params():
    active = _FakeActive(_FakeAction(params={"duration": 12.5}))
    ex = Executor(active=active)
    assert ex.duration == 12.5


def test_default_phase_return_shapes():
    ex = _make()
    pre = asyncio.run(ex._pre_exec())
    assert pre == {"error": ErrorCodes.none}

    exec_ = asyncio.run(ex._exec())
    assert exec_ == {"data": {}, "error": ErrorCodes.none}

    poll = asyncio.run(ex._poll())
    assert poll == {"data": {}, "error": ErrorCodes.none, "status": HloStatus.finished}

    post = asyncio.run(ex._post_exec())
    assert post == {"data": {}, "error": ErrorCodes.none}

    stop = asyncio.run(ex._manual_stop())
    assert stop == {"error": ErrorCodes.none}


def test_set_binders_rebind_phases():
    ex = _make()

    async def pre(self):
        return {"error": ErrorCodes.none, "bound": "pre"}

    async def exec_(self):
        return {"data": {"v": 1}, "error": ErrorCodes.none}

    async def poll(self):
        return {"data": {}, "error": ErrorCodes.none, "status": HloStatus.active}

    async def post(self):
        return {"data": {"done": True}, "error": ErrorCodes.none}

    async def stop(self):
        return {"error": ErrorCodes.stop}

    ex.set_pre_exec(pre)
    ex.set_exec(exec_)
    ex.set_poll(poll)
    ex.set_post_exec(post)
    ex.set_manual_stop(stop)

    assert asyncio.run(ex._pre_exec())["bound"] == "pre"
    assert asyncio.run(ex._exec())["data"] == {"v": 1}
    assert asyncio.run(ex._poll())["status"] == HloStatus.active
    assert asyncio.run(ex._post_exec())["data"] == {"done": True}
    assert asyncio.run(ex._manual_stop())["error"] == ErrorCodes.stop


def test_bound_method_receives_self():
    ex = _make()
    seen = {}

    async def pre(self):
        seen["self"] = self
        return {"error": ErrorCodes.none}

    ex.set_pre_exec(pre)
    asyncio.run(ex._pre_exec())
    assert seen["self"] is ex
