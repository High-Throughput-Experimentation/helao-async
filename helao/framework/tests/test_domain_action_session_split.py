"""Tests for ActionSession split / substitute / manual transitions (Wave 4.1).

These exercise the fork/substitute/manual-promotion transitions ported from the
legacy ``Active.split`` / ``split_and_keep_active`` /
``split_and_finish_prev_uuids`` / ``substitute`` / ``finish_manual_action``.

All I/O goes through the injected fakes (``Storage`` / ``EventSink`` / ``Clock`` /
``Transport``) and the uuid/clock are injected so output is deterministic.
"""

import asyncio
from datetime import datetime
from itertools import count
from uuid import UUID

from helao.framework.models.hlostatus import HloStatus
from helao.framework.domain.run_models import RunAction
from helao.framework.domain.executor import Executor
from helao.framework.domain.action_session import ActionSession

from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.fakes.eventsink import FakeEventSink
from helao.framework.adapters.fakes.clock import FakeClock
from helao.framework.adapters.fakes.transport import FakeTransport

FIXED_NOW = datetime(2026, 6, 22, 14, 5, 6)
SPLIT_NOW = datetime(2026, 6, 22, 14, 9, 9)
FIXED_UUID = UUID("00000000-0000-0000-0000-0000000000aa")
NEW_UUID = UUID("00000000-0000-0000-0000-0000000000bb")
FILE_CONN = UUID("00000000-0000-0000-0000-0000000000ff")


def _run_action(**overrides):
    kwargs = dict(
        action_name="dummy_act",
        action_uuid=FIXED_UUID,
        action_timestamp=FIXED_NOW,
        sequence_timestamp=FIXED_NOW,
        experiment_timestamp=FIXED_NOW,
        sequence_uuid=FIXED_UUID,
        experiment_uuid=FIXED_UUID,
        sequence_name="seq",
        experiment_name="exp",
        sequence_output_dir="26.25/0622/x__seq",
        experiment_output_dir="26.25/0622/x__seq/exp",
        action_output_dir="26.25/0622/x__seq/exp/0__0__srv__dummy_act",
        save_act=True,
        save_data=True,
        file_conn_keys=[FILE_CONN],
    )
    kwargs.update(overrides)
    return RunAction(**kwargs)


def _make_session(action=None, now_values=None, uuid_values=None):
    storage = FakeStorage()
    eventsink = FakeEventSink()
    clock = FakeClock()
    transport = FakeTransport()
    if action is None:
        action = _run_action()

    class _Wrap:
        def __init__(self, act):
            self.action = act

    executor = Executor(active=_Wrap(action))

    # Constant factories: split() mints one timestamp/uuid for the new action and
    # finish() stamps a finished timestamp, so the factories are called more than
    # once. The tests assert on the (single) value these constants return.
    now_value = now_values[0] if now_values else SPLIT_NOW
    uuid_value = uuid_values[0] if uuid_values else NEW_UUID

    session = ActionSession(
        action,
        storage=storage,
        eventsink=eventsink,
        clock=clock,
        executor=executor,
        transport=transport,
        now_factory=lambda: now_value,
        uuid_factory=lambda: uuid_value,
    )
    return session, storage, eventsink, clock, transport


# --- split ---------------------------------------------------------------------


def test_split_increments_action_split_and_reinits_identity():
    session, storage, eventsink, clock, transport = _make_session(
        now_values=[SPLIT_NOW], uuid_values=[NEW_UUID]
    )
    # open the original file connection so split has something to close
    asyncio.run(session.open_file(FILE_CONN, header="hdr"))

    asyncio.run(session.split())

    # new action has incremented split, new uuid + timestamp
    assert session.action.action_split == 1
    assert session.action.action_uuid == NEW_UUID
    assert session.action.action_timestamp == SPLIT_NOW
    # the previous action lives on in action_list (siblings, newest first)
    assert len(session.action_list) == 2
    assert session.action_list[0] is session.action


def test_split_links_parent_and_child_uuids():
    session, *_ = _make_session(now_values=[SPLIT_NOW], uuid_values=[NEW_UUID])
    asyncio.run(session.open_file(FILE_CONN, header=""))
    asyncio.run(session.split())

    new_action = session.action_list[0]
    prev_action = session.action_list[1]
    assert new_action.parent_action_uuid == prev_action.action_uuid
    assert prev_action.child_action_uuid == new_action.action_uuid
    assert HloStatus.split in prev_action.action_status


def test_split_opens_new_file_conns_and_closes_old():
    session, storage, *_ = _make_session(now_values=[SPLIT_NOW], uuid_values=[NEW_UUID])
    old_handle = asyncio.run(session.open_file(FILE_CONN, header="hdr"))
    asyncio.run(session.split())

    # old handle closed
    assert old_handle.closed is True
    # the new action has a fresh file_conn key and a corresponding open handle
    assert len(session.action.file_conn_keys) == 1
    new_key = session.action.file_conn_keys[0]
    assert new_key != FILE_CONN
    assert new_key in session._open_handles
    # a new HLO buffer was opened for the new action
    assert len(storage.hlo_buffers) == 2


def test_split_resets_samples_and_counters():
    session, *_ = _make_session(now_values=[SPLIT_NOW], uuid_values=[NEW_UUID])
    asyncio.run(session.open_file(FILE_CONN, header=""))
    session.num_data_queued = 5
    session.num_data_written = 5
    asyncio.run(session.split())
    assert session.action.samples_in == []
    assert session.action.samples_out == []
    assert session.action.files == []


def test_split_and_keep_active_keeps_previous_open():
    session, *_ = _make_session(now_values=[SPLIT_NOW], uuid_values=[NEW_UUID])
    asyncio.run(session.open_file(FILE_CONN, header=""))
    asyncio.run(session.split_and_keep_active())
    # previous action NOT finished
    prev = session.action_list[1]
    assert HloStatus.finished not in prev.action_status


def test_split_and_finish_prev_uuids_finishes_previous():
    session, *_ = _make_session(now_values=[SPLIT_NOW], uuid_values=[NEW_UUID])
    asyncio.run(session.open_file(FILE_CONN, header=""))
    asyncio.run(session.split_and_finish_prev_uuids())
    prev = session.action_list[1]
    assert HloStatus.finished in prev.action_status
    # the new (current) action stays unfinished
    assert HloStatus.finished not in session.action.action_status


# --- substitute ----------------------------------------------------------------


def test_substitute_closes_all_open_handles():
    session, storage, *_ = _make_session()
    h1 = asyncio.run(session.open_file(FILE_CONN, header=""))
    other = UUID("00000000-0000-0000-0000-0000000000ee")
    h2 = asyncio.run(session.open_file(other, header=""))
    asyncio.run(session.substitute())
    assert h1.closed is True
    assert h2.closed is True
    assert session._open_handles == {}


# --- manual action promotion + finish_manual_action ----------------------------


def test_manual_action_writes_synthetic_exp_and_seq_meta():
    # an action with no parent timestamps auto-promotes to manual on myinit
    storage = FakeStorage()
    eventsink = FakeEventSink()
    clock = FakeClock()
    action = RunAction(
        action_name="manual_act",
        save_act=True,
        save_data=False,
    )

    class _Wrap:
        def __init__(self, act):
            self.action = act

    executor = Executor(active=_Wrap(action))
    session = ActionSession(
        action,
        storage=storage,
        eventsink=eventsink,
        clock=clock,
        executor=executor,
        now_factory=lambda: FIXED_NOW,
        uuid_factory=lambda: FIXED_UUID,
    )
    asyncio.run(session.promote_manual())
    assert session.action.manual_action is True
    assert session.action.access == "manual"

    asyncio.run(session.finish_manual_action())
    # synthetic .seq and .exp meta written for the manual run
    suffixes = [relpath.rsplit(".", 1)[-1] for relpath in storage.meta_docs]
    assert "seq" in suffixes
    assert "exp" in suffixes


def test_finish_manual_action_noop_when_not_manual():
    session, storage, *_ = _make_session()
    asyncio.run(session.finish_manual_action())
    # no synthetic exp/seq written for a non-manual action
    suffixes = [relpath.rsplit(".", 1)[-1] for relpath in storage.meta_docs]
    assert "seq" not in suffixes
    assert "exp" not in suffixes
