"""Tests for the ActionSession core state machine (domain/action_session.py).

``ActionSession`` is the pure port of the legacy ``Active`` wrapper: it drives
an :class:`Executor` through its phases, streams data and status through the
injected ports, and tracks the run-action's lifecycle. All I/O goes through the
injected fakes (``Storage`` / ``EventSink`` / ``Clock`` / ``Transport``); no real
filesystem or network is touched.

This module covers the init -> active -> finish HAPPY PATH for a oneoff executor.
split / substitute / manual / full drain semantics arrive in Wave 4.
"""

import asyncio
from datetime import datetime
from uuid import UUID

import pytest

from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.sample import NoneSample, SolidSample
from helao.framework.ports.eventsink import STATUS_CHANNEL, DATA_CHANNEL
from helao.framework.domain.run_models import RunAction
from helao.framework.domain.executor import Executor
from helao.framework.domain.action_session import ActionSession

from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.fakes.eventsink import FakeEventSink
from helao.framework.adapters.fakes.clock import FakeClock
from helao.framework.adapters.fakes.transport import FakeTransport

FIXED_NOW = datetime(2026, 6, 22, 14, 5, 6)
FIXED_UUID = UUID("00000000-0000-0000-0000-0000000000aa")
FILE_CONN = UUID("00000000-0000-0000-0000-0000000000ff")


def _run_action(**overrides):
    kwargs = dict(
        action_name="dummy_act",
        action_uuid=FIXED_UUID,
        action_timestamp=FIXED_NOW,
        sequence_timestamp=FIXED_NOW,
        experiment_timestamp=FIXED_NOW,
        sequence_name="seq",
        experiment_name="exp",
        action_output_dir="26.25/0622/x__0__srv__dummy_act",
        save_act=True,
        save_data=True,
        file_conn_keys=[FILE_CONN],
    )
    kwargs.update(overrides)
    return RunAction(**kwargs)


def _make_session(executor_kwargs=None, exec_data=None):
    storage = FakeStorage()
    eventsink = FakeEventSink()
    clock = FakeClock()
    transport = FakeTransport()
    action = _run_action()

    class _Wrap:
        def __init__(self, act):
            self.action = act

    executor = Executor(active=_Wrap(action), **(executor_kwargs or {}))
    if exec_data is not None:

        async def _exec(self):
            return {"data": exec_data, "error": ErrorCodes.none}

        executor.set_exec(_exec)

    session = ActionSession(
        action,
        storage=storage,
        eventsink=eventsink,
        clock=clock,
        executor=executor,
        transport=transport,
    )
    return session, storage, eventsink, clock, executor


# --- construction --------------------------------------------------------------


def test_construct_initial_state():
    session, storage, eventsink, clock, executor = _make_session()
    assert session.action.action_uuid == FIXED_UUID
    assert session.action_list == [session.action]
    assert session.num_data_queued == 0
    assert session.num_data_written == 0
    assert session.manual_stop is False


# --- myinit --------------------------------------------------------------------


def test_myinit_creates_output_and_emits_initial_status():
    session, storage, eventsink, clock, executor = _make_session()
    asyncio.run(session.myinit())
    # output created via storage (meta written for the .act file)
    assert len(storage.meta_docs) >= 1
    # initial status emitted on the status channel
    assert len(eventsink.statuses) == 1


def test_myinit_skips_meta_when_save_act_false():
    storage = FakeStorage()
    eventsink = FakeEventSink()
    clock = FakeClock()
    action = _run_action(save_act=False, save_data=False)

    class _Wrap:
        def __init__(self, act):
            self.action = act

    executor = Executor(active=_Wrap(action))
    session = ActionSession(
        action, storage=storage, eventsink=eventsink, clock=clock, executor=executor
    )
    asyncio.run(session.myinit())
    assert storage.meta_docs == {}
    # still emits the initial status
    assert len(eventsink.statuses) == 1


# --- add_status / enqueue_data -------------------------------------------------


def test_add_status_emits_for_blocking_action():
    session, storage, eventsink, clock, executor = _make_session()
    asyncio.run(session.add_status())
    assert len(eventsink.statuses) == 1


def test_add_status_noop_for_nonblocking():
    session, *_ = _make_session()
    session.action.nonblocking = True
    eventsink = session.eventsink
    asyncio.run(session.add_status())
    assert eventsink.statuses == []


def test_enqueue_data_bumps_counter_when_data_present():
    session, storage, eventsink, clock, executor = _make_session()
    asyncio.run(session.enqueue_data({FILE_CONN: {"v": 1}}))
    assert session.num_data_queued == 1
    assert len(eventsink.data) == 1


def test_enqueue_data_no_bump_when_empty():
    session, storage, eventsink, clock, executor = _make_session()
    asyncio.run(session.enqueue_data({}))
    assert session.num_data_queued == 0


# --- write_file ----------------------------------------------------------------


def test_write_file_records_storage_write():
    session, storage, eventsink, clock, executor = _make_session()
    relpath = asyncio.run(
        session.write_file(output_str="hello", file_type="aux_type", filename="aux.csv")
    )
    assert relpath is not None
    assert relpath in storage.hlo_buffers
    assert "hello" in storage.hlo_buffers[relpath]


# --- append_sample -------------------------------------------------------------


def test_append_sample_mutates_and_emits_status():
    session, storage, eventsink, clock, executor = _make_session()
    smp = SolidSample(sample_no=1, plate_id=1)
    asyncio.run(session.append_sample([smp], "in"))
    assert len(session.action.samples_in) == 1
    assert len(eventsink.statuses) == 1


def test_append_sample_skips_none_sample():
    session, storage, eventsink, clock, executor = _make_session()
    asyncio.run(session.append_sample([NoneSample()], "out"))
    assert session.action.samples_out == []


# --- full init -> active -> finish happy path ----------------------------------


def test_action_loop_drives_oneoff_and_finishes():
    session, storage, eventsink, clock, executor = _make_session(
        exec_data={"signal": 42}
    )
    asyncio.run(session.myinit())
    result = asyncio.run(session.action_loop_task(executor))

    # exec-phase data was enqueued through the data channel
    assert session.num_data_queued >= 1
    assert len(eventsink.data) >= 1

    # counters balance after finish drains the queue
    assert session.num_data_queued == session.num_data_written

    # final status is finished
    assert HloStatus.finished in session.action.action_status
    # a finished status was emitted
    statuses = eventsink.statuses
    assert any(
        HloStatus.finished.value in [str(s) for s in p.get("action_status", [])]
        for p in statuses
    )
    assert result is session.action


def test_construct_base_defaults_none_and_action_task_none():
    session, *_ = _make_session()
    assert session.base is None
    assert session.action_task is None


# --- start_executor ------------------------------------------------------------


class _FakeBase:
    """Minimal duck-typed base: executors registry + live-buffer hooks."""

    def __init__(self):
        self.executors = {}
        self.put_messages = []
        self.lbuf_sentinel = (123, 456.0)

    async def put_lbuf(self, message):
        self.put_messages.append(message)

    def get_lbuf(self, buf_key):
        return self.lbuf_sentinel


def _make_session_with_base(base, exec_data=None):
    storage = FakeStorage()
    eventsink = FakeEventSink()
    clock = FakeClock()
    transport = FakeTransport()
    action = _run_action()

    class _Wrap:
        def __init__(self, act):
            self.action = act

    executor = Executor(active=_Wrap(action))
    if exec_data is not None:

        async def _exec(self):
            return {"data": exec_data, "error": ErrorCodes.none}

        executor.set_exec(_exec)

    session = ActionSession(
        action,
        storage=storage,
        eventsink=eventsink,
        clock=clock,
        executor=executor,
        transport=transport,
        base=base,
    )
    return session, executor


def test_start_executor_registers_and_spawns_task():
    async def _run():
        base = _FakeBase()
        session, executor = _make_session_with_base(base, exec_data={"v": 1})
        await session.myinit()
        result = session.start_executor(executor)
        # returns the active action dict
        assert result == session.action.as_dict()
        # executor registered in base.executors keyed by exec_id
        assert base.executors[executor.exec_id] is executor
        # self.executor set + a task created
        assert session.executor is executor
        assert session.action_task is not None
        # drain the background task so it doesn't leak (oneoff finishes promptly)
        finished = await session.action_task
        assert finished is session.action
        assert HloStatus.finished in session.action.action_status

    asyncio.run(_run())


def test_start_executor_without_base_skips_registry():
    async def _run():
        session, storage, eventsink, clock, executor = _make_session(
            exec_data={"v": 1}
        )
        await session.myinit()
        result = session.start_executor(executor)
        assert result == session.action.as_dict()
        assert session.executor is executor
        # base is None -> no registry write, no error
        assert session.base is None
        await session.action_task

    asyncio.run(_run())


# --- put_lbuf / get_lbuf delegation --------------------------------------------


def test_put_lbuf_delegates_to_base():
    async def _run():
        base = _FakeBase()
        session, _executor = _make_session_with_base(base)
        await session.put_lbuf({"temp": 25})
        assert base.put_messages == [{"temp": 25}]

    asyncio.run(_run())


def test_get_lbuf_delegates_to_base():
    base = _FakeBase()
    session, _executor = _make_session_with_base(base)
    assert session.get_lbuf("temp") == base.lbuf_sentinel


def test_poll_executor_runs_until_terminal_then_finishes():
    session, storage, eventsink, clock, executor = _make_session(
        executor_kwargs={"oneoff": False, "poll_rate": 0}
    )
    calls = {"n": 0}

    async def _poll(self):
        calls["n"] += 1
        if calls["n"] < 3:
            return {"data": {"i": calls["n"]}, "error": ErrorCodes.none, "status": HloStatus.active}
        return {"data": {}, "error": ErrorCodes.none, "status": HloStatus.finished}

    executor.set_poll(_poll)
    asyncio.run(session.myinit())
    asyncio.run(session.action_loop_task(executor))

    assert calls["n"] == 3
    assert session.num_data_queued == session.num_data_written
    assert HloStatus.finished in session.action.action_status
