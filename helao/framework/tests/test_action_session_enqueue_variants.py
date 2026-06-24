"""Tests for ActionSession.enqueue_data_dflt / enqueue_data_nowait + Active alias.

TDD: written BEFORE implementation so these fail first.

Covers:
- enqueue_data_dflt routes data through the default file_conn_key and bumps counters.
- enqueue_data_nowait schedules the async enqueue without the caller awaiting.
- Active alias in base_api resolves to ActionSession.
"""
import asyncio
from datetime import datetime
from uuid import UUID

import pytest

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


def _make_session(**action_overrides):
    storage = FakeStorage()
    eventsink = FakeEventSink()
    clock = FakeClock()
    transport = FakeTransport()
    action = _run_action(**action_overrides)

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
        transport=transport,
    )
    return session


# ---------------------------------------------------------------------------
# enqueue_data_dflt
# ---------------------------------------------------------------------------


def test_enqueue_data_dflt_bumps_counter():
    """enqueue_data_dflt with a non-empty datadict must increment num_data_queued."""
    session = _make_session()
    asyncio.run(session.enqueue_data_dflt({"x": 1}))
    assert session.num_data_queued == 1


def test_enqueue_data_dflt_emits_data_event():
    """enqueue_data_dflt must emit one data event on the eventsink."""
    session = _make_session()
    asyncio.run(session.enqueue_data_dflt({"x": 1}))
    assert len(session.eventsink.data) == 1


def test_enqueue_data_dflt_payload_carries_default_key():
    """The emitted data payload must contain the default file_conn_key as a key in the datamodel."""
    session = _make_session()
    asyncio.run(session.enqueue_data_dflt({"x": 1}))
    payload = session.eventsink.data[0]
    # payload is a DataPackageModel.as_dict(); datamodel.data is the keyed mapping
    datamodel_data = payload["datamodel"]["data"]
    assert str(FILE_CONN) in datamodel_data or FILE_CONN in datamodel_data


def test_enqueue_data_dflt_empty_dict_still_bumps():
    """enqueue_data_dflt with empty datadict wraps to {key: {}}, which is truthy.

    The outer mapping has one entry (the default key), so ``enqueue_data`` sees
    non-empty data and bumps the counter. This is consistent with legacy
    ``Active.enqueue_data_dflt`` semantics.
    """
    session = _make_session()
    asyncio.run(session.enqueue_data_dflt({}))
    # {FILE_CONN: {}} is truthy — counter bumps
    assert session.num_data_queued == 1


# ---------------------------------------------------------------------------
# enqueue_data_nowait
# ---------------------------------------------------------------------------


def test_enqueue_data_nowait_bumps_counter_after_yield():
    """enqueue_data_nowait must schedule the emit; after a yield the counter is bumped."""
    async def _run():
        session = _make_session()
        session.enqueue_data_nowait({FILE_CONN: {"y": 2}})
        # before yielding: scheduled but not yet run
        # after one yield: the task should have executed
        await asyncio.sleep(0)
        return session

    session = asyncio.run(_run())
    assert session.num_data_queued == 1


def test_enqueue_data_nowait_emits_data_after_yield():
    """enqueue_data_nowait must emit one data event after the loop yields."""
    async def _run():
        session = _make_session()
        session.enqueue_data_nowait({FILE_CONN: {"y": 2}})
        await asyncio.sleep(0)
        return session

    session = asyncio.run(_run())
    assert len(session.eventsink.data) == 1


def test_enqueue_data_nowait_accepts_datamodel():
    """enqueue_data_nowait must accept a DataModel directly (passes through to enqueue_data)."""
    from helao.framework.models.data import DataModel
    from helao.framework.models.hlostatus import HloStatus

    async def _run():
        session = _make_session()
        dm = DataModel(data={FILE_CONN: {"z": 3}}, errors=[], status=HloStatus.active)
        session.enqueue_data_nowait(dm)
        await asyncio.sleep(0)
        return session

    session = asyncio.run(_run())
    assert session.num_data_queued == 1


# ---------------------------------------------------------------------------
# Active alias in base_api
# ---------------------------------------------------------------------------


def test_active_alias_is_action_session():
    """Active imported from base_api must be the same class as ActionSession."""
    from helao.framework.app.base_api import Active
    assert Active is ActionSession


def test_active_in_base_api_all():
    """Active must be listed in base_api.__all__."""
    import helao.framework.app.base_api as ba
    assert "Active" in ba.__all__
