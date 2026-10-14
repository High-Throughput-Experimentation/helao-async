"""``ActionHost.shutdown`` runs the driver hooks once per process.

A group stop (Ctrl-X) reaches every host twice: the launcher's ``POST
/shutdown``, then uvicorn's lifespan ``shutdown`` event when the process is
signalled. On hte-ecms-03 (2026-10-14) the second run made each Alicat MFC
server re-send ``hold_valve_closed`` to serial ports the first run had closed;
the error went to the console, and every MFC server took ~2.5 s longer to die.
"""

import asyncio

import pytest

from helao.hexagon.app.action_host import ActionHost


class CountingDriver:
    def __init__(self, gate: asyncio.Event | None = None):
        self.calls = 0
        self.finished = 0
        self.gate = gate

    async def async_shutdown(self):
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("second safe-state command on a closed port")
        if self.gate is not None:
            await self.gate.wait()
        self.finished += 1
        return "closed"


class StubQueue:
    async def close(self):
        pass


def _host(driver) -> ActionHost:
    host = ActionHost.__new__(ActionHost)  # no config, sockets or startup
    host._shutdown_task = None
    host.poller = None
    host.driver = driver
    host.status_logger = host.bufferer = host.regular_updater = None
    host.status_q = host.data_q = host.live_q = StubQueue()  # type: ignore
    host.fault_file = None

    async def no_subscribers():
        pass

    host.detach_subscribers = no_subscribers  # type: ignore[method-assign]
    return host


@pytest.mark.asyncio
async def test_post_shutdown_then_lifespan_runs_driver_hooks_once():
    driver = CountingDriver()
    host = _host(driver)
    first = await host.shutdown()  # POST /shutdown
    second = await host.shutdown()  # lifespan event on the signal
    assert driver.calls == 1
    assert first == second and first["async_shutdown"] == "closed"


@pytest.mark.asyncio
async def test_concurrent_calls_share_one_run():
    driver = CountingDriver()
    host = _host(driver)
    a, b = await asyncio.gather(host.shutdown(), host.shutdown())
    assert driver.calls == 1 and a == b


@pytest.mark.asyncio
async def test_cancelled_caller_does_not_abort_the_shutdown():
    """uvicorn may cancel the /shutdown request mid-hook; the hooks must finish."""
    gate = asyncio.Event()
    driver = CountingDriver(gate)
    host = _host(driver)
    request = asyncio.create_task(host.shutdown())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    request.cancel()
    gate.set()
    result = await host.shutdown()
    assert result["async_shutdown"] == "closed"
    assert driver.calls == 1 and driver.finished == 1
