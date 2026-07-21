"""Unit tests for `helao.hexagon.adapters.legacy.pal_trigger` (P3a-PAL
slice 5): `NidaqmxPalTrigger` + `NullPalTrigger`.

`wait_for_triggers`/`clear_queues` are pure-asyncio-queue logic with zero
NI-DAQmx dependency, so they're fully Linux-testable by feeding the
adapter's internal queues directly. `start_polling`'s poll loop needs the
real NI-DAQmx driver (confirmed absent in this env: bare `nidaqmx.Task()`
construction raises `DaqNotFoundError`, not just "no channels configured")
-- station-gated at runtime, but the graceful failure path (the poll
loop's own try/except catches exactly this and logs, matching legacy
behavior at a non-NI-DAQmx-equipped station) IS exercised here to prove
`start_polling`/`stop_polling` never raise.

`pytest-asyncio` is not installed in this env (see test_pal_reconciliation.
py's docstring), so async bodies run via `asyncio.run(...)` from plain
`def test_*` wrappers.
"""

import asyncio

from helao.core.error import ErrorCodes
from helao.hexagon.adapters.legacy.pal_trigger import NidaqmxPalTrigger, NullPalTrigger
from helao.hexagon.ports.pal_trigger import PalTriggerPort


def test_nidaqmx_trigger_is_pal_trigger_port():
    assert isinstance(NidaqmxPalTrigger("a", "b", "c", timeout=1.0), PalTriggerPort)


def test_null_trigger_is_pal_trigger_port():
    assert isinstance(NullPalTrigger(), PalTriggerPort)


def test_construct_disconnected_no_nidaqmx_touch():
    # construction must never import/touch nidaqmx -- only start_polling's
    # poll loop does, lazily.
    trigger = NidaqmxPalTrigger(
        trigger_start="port0/line0",
        trigger_continue="port0/line1",
        trigger_done="port0/line2",
        timeout=5.0,
    )
    assert trigger._poll_task is None


def test_wait_for_triggers_happy_path():
    async def _run():
        trigger = NidaqmxPalTrigger("s", "c", "d", timeout=1.0)
        trigger._startq.put_nowait(100)
        trigger._continueq.put_nowait(200)
        trigger._doneq.put_nowait(300)

        error, start, cont, done = await trigger.wait_for_triggers()

        assert error is ErrorCodes.none
        assert (start, cont, done) == (100, 200, 300)

    asyncio.run(_run())


def test_wait_for_triggers_start_timeout():
    async def _run():
        trigger = NidaqmxPalTrigger("s", "c", "d", timeout=0.05)

        error, start, cont, done = await trigger.wait_for_triggers()

        assert error is ErrorCodes.start_timeout
        assert (start, cont, done) == (None, None, None)

    asyncio.run(_run())


def test_wait_for_triggers_continue_timeout_preserves_start():
    async def _run():
        trigger = NidaqmxPalTrigger("s", "c", "d", timeout=0.05)
        trigger._startq.put_nowait(111)

        error, start, cont, done = await trigger.wait_for_triggers()

        assert error is ErrorCodes.continue_timeout
        assert start == 111
        assert (cont, done) == (None, None)

    asyncio.run(_run())


def test_wait_for_triggers_done_timeout_preserves_start_and_continue():
    async def _run():
        trigger = NidaqmxPalTrigger("s", "c", "d", timeout=0.05)
        trigger._startq.put_nowait(111)
        trigger._continueq.put_nowait(222)

        error, start, cont, done = await trigger.wait_for_triggers()

        assert error is ErrorCodes.done_timeout
        assert (start, cont) == (111, 222)
        assert done is None

    asyncio.run(_run())


def test_clear_queues_drains_stale_entries():
    async def _run():
        trigger = NidaqmxPalTrigger("s", "c", "d", timeout=1.0)
        trigger._startq.put_nowait(1)
        trigger._continueq.put_nowait(2)
        trigger._doneq.put_nowait(3)

        await trigger.clear_queues()

        assert trigger._startq.empty()
        assert trigger._continueq.empty()
        assert trigger._doneq.empty()

    asyncio.run(_run())


def test_start_stop_polling_graceful_without_nidaqmx_hardware():
    """No real NI-DAQmx driver in this env -- the poll loop's own
    try/except must catch `DaqNotFoundError` and exit cleanly (matching
    legacy behavior at a station without the NI-DAQmx runtime), so
    start_polling/stop_polling never raise."""

    async def _run():
        trigger = NidaqmxPalTrigger("port0/line0", "port0/line1", "port0/line2", 1.0)
        calls = {"realtime": 0}

        def realtime_nowait():
            calls["realtime"] += 1
            return 42

        trigger.start_polling(realtime_nowait, is_measuring=lambda: True)
        assert trigger._poll_task is not None

        # give the poll task a moment to hit DaqNotFoundError and finish
        for _ in range(20):
            await asyncio.sleep(0.01)
            if trigger._poll_task.done():
                break

        trigger.stop_polling()
        assert trigger._poll_task is None
        # never touched the DataSink-realtime callable since NI-DAQmx
        # construction failed before any channel read
        assert calls["realtime"] == 0

    asyncio.run(_run())


def test_null_trigger_start_polling_is_noop():
    trigger = NullPalTrigger()
    trigger.start_polling(lambda: 1, lambda: True)
    trigger.stop_polling()  # must not raise


def test_null_trigger_clear_queues_is_noop():
    async def _run():
        await NullPalTrigger().clear_queues()  # must not raise

    asyncio.run(_run())


def test_null_trigger_wait_for_triggers_returns_immediately():
    async def _run():
        error, start, cont, done = await NullPalTrigger().wait_for_triggers()
        assert error is ErrorCodes.none
        assert (start, cont, done) == (None, None, None)

    asyncio.run(_run())
