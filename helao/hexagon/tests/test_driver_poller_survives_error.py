"""A raising ``get_data`` must not kill the polling task for good."""

import asyncio
import logging

import pytest

from helao.core.drivers.helao_driver import DriverPoller, DriverResponse


class _Flaky(DriverPoller):
    def __init__(self, failures):
        self.calls = 0
        self.failures = failures
        super().__init__(driver=None, wait_time=0.01)

    def get_data(self) -> DriverResponse:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("transient read failure")
        return DriverResponse(data={"x": self.calls})


@pytest.mark.asyncio
async def test_polling_continues_after_get_data_raises(caplog):
    caplog.set_level(logging.INFO)
    poller = _Flaky(failures=3)
    # DriverPoller's logger has propagate=False; capture via the root-free path.
    from helao.core.drivers import helao_driver

    helao_driver.LOGGER.addHandler(caplog.handler)
    try:
        for _ in range(100):
            if "x" in poller.live_dict:
                break
            await asyncio.sleep(0.02)
        await poller.stop()
    finally:
        helao_driver.LOGGER.removeHandler(caplog.handler)
    assert poller.live_dict.get("x", 0) >= 4
    assert sum(1 for r in caplog.records if r.exc_info) == 1, "traceback every failure"
    assert any("recovered after 3 failures" in r.getMessage() for r in caplog.records)
