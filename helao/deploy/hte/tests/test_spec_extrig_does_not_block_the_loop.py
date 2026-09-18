"""SM303 DLL calls must never run on the event loop.

At eche10 an ``acquire_spec_extrig`` with (suspected) miswired trigger lines
took the whole SPEC_T server down: the action hung and *every* endpoint
stopped answering, private ones like /list_executors included. The log ends
one line after "exiting executor polling loop", which is ``_post_exec``.

The mechanism: ``_poll`` reads through ``run_in_executor``, but ``wait_for``
cancels the await, not the thread, so a read waiting on a trigger that never
arrives stays parked inside ``spReadDataEx``. The vendor DLL serializes on the
device handle, so the ``spSetTrgEx`` and ``spCloseGivenChannel`` that
``_post_exec`` then ran *inline on the event loop* blocked behind it -- and a
blocked event loop is a server that answers nothing.

A hardware fault should cost the action, not the API.
"""

import asyncio
import time

import pytest

from helao.deploy.hte.drivers.spec import spectral_products_driver as spec_driver
from helao.deploy.hte.servers.action import spec_server
from helao.deploy.hte.servers.action.spec_server import SM303Exec


class _Spec:
    """Stands in for the ctypes DLL handle."""

    def __init__(self, block_s: float):
        self.block_s = block_s
        self.closed = 0

    def spCloseGivenChannel(self, dev_num):
        time.sleep(self.block_s)
        self.closed += 1
        return 1


class _Driver:
    """An SM303 whose DLL calls block, the way the device does mid-trigger."""

    def __init__(self, block_s: float = 0.4):
        self.spec = _Spec(block_s)
        self.dev_num = 0
        self.block_s = block_s
        self.trigger_duration = 0.0
        self.start_margin = 0.05
        self.start_time = 0.0
        self.spec_time = 0.0
        self.data = []
        self.reads = 0
        self.unset_calls = 0

    def unset_external_trigger(self):
        time.sleep(self.block_s)
        self.unset_calls += 1

    def read_data(self):
        self.reads += 1
        time.sleep(self.block_s)
        return 1


def _exec_with(driver) -> SM303Exec:
    """An SM303Exec bound to ``driver``, with no Executor framework around it."""
    ex = object.__new__(SM303Exec)
    ex.driver = driver
    ex._read_future = None
    return ex


async def _tick(counter: list, stop: asyncio.Event):
    """Stands in for every other coroutine on the loop -- a request handler."""
    while not stop.is_set():
        counter.append(1)
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_post_exec_does_not_freeze_the_event_loop():
    driver = _Driver(block_s=0.4)
    ex = _exec_with(driver)

    counter: list = []
    stop = asyncio.Event()
    ticker = asyncio.create_task(_tick(counter, stop))
    await asyncio.sleep(0)

    await ex._post_exec()
    stop.set()
    await ticker

    # Two blocking calls of 0.4 s. Run inline they yield nothing at all;
    # off the loop the ticker keeps running throughout.
    assert driver.unset_calls == 1 and driver.spec.closed == 1
    assert len(counter) > 10, (
        f"the loop only ran {len(counter)} times during 0.8s of device calls; "
        "they are still executing inline"
    )


@pytest.mark.asyncio
async def test_a_device_call_that_never_returns_is_bounded(monkeypatch):
    monkeypatch.setattr(spec_driver, "DEVICE_CALL_TIMEOUT_S", 0.2)
    # 2 s stands for "forever" against a 0.2 s ceiling -- an order of
    # magnitude is enough to prove the bound, and the test does not have to
    # wait out a parked thread at loop teardown to prove it.
    driver = _Driver(block_s=2.0)
    ex = _exec_with(driver)

    started = asyncio.get_running_loop().time()
    result = await asyncio.wait_for(ex._post_exec(), 5.0)
    elapsed = asyncio.get_running_loop().time() - started

    # Returns, so the action finalizes and the executor is unregistered; the
    # worker thread stays parked until the DLL releases it.
    assert result["error"] == spec_server.ErrorCodes.none
    assert elapsed < 2.0, f"_post_exec took {elapsed:.1f}s"


@pytest.mark.asyncio
async def test_manual_stop_is_also_off_the_loop(monkeypatch):
    monkeypatch.setattr(spec_driver, "DEVICE_CALL_TIMEOUT_S", 0.2)
    driver = _Driver(block_s=2.0)
    ex = _exec_with(driver)

    # The abort path is reached precisely when the device is misbehaving, so
    # it is the last place that should block.
    await asyncio.wait_for(ex._manual_stop(), 5.0)


@pytest.mark.asyncio
async def test_poll_does_not_stack_a_second_read_thread():
    driver = _Driver(block_s=1.0)
    driver.trigger_duration = 0.0
    driver.start_margin = 0.05
    ex = _exec_with(driver)

    for _ in range(3):
        driver.start_time = time.time()
        driver.spec_time = driver.start_time
        await ex._poll()

    # Every poll used to submit another blocking read; at poll_rate 0.01 that
    # is 100 parked pool workers a second.
    assert driver.reads == 1, f"{driver.reads} reads were submitted"
