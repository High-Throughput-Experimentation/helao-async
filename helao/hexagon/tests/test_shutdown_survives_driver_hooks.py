"""A driver teardown hook that raises must not abort host shutdown.

Since a raising startup ``connect()`` no longer stops the server, a host can carry a
driver that never connected, and its ``shutdown``/``async_shutdown`` may fail on the
closed device. Shutdown still has to finish: return its ``retvals``, log each failure
at ERROR with the traceback, and close the fault file.
"""

import logging
import tempfile
from typing import Any

from fastapi.testclient import TestClient

from helao.core.drivers.helao_driver import DriverResponse, HelaoDriver


class FailingTeardownDriver(HelaoDriver):
    def connect(self) -> DriverResponse:
        return DriverResponse()

    def get_status(self) -> DriverResponse:
        return DriverResponse()

    def stop(self) -> DriverResponse:
        return DriverResponse()

    def reset(self) -> DriverResponse:
        return DriverResponse()

    def disconnect(self) -> DriverResponse:
        return DriverResponse()

    def shutdown(self):
        raise RuntimeError("shutdown hook failed")

    async def async_shutdown(self):
        raise RuntimeError("async_shutdown hook failed")


def _host():
    from helao.hexagon.app.action_host import ActionHost
    from helao.hexagon.app.wiring import PortWiring

    cfg = {
        "root": tempfile.mkdtemp(prefix="helao_shutdown_hooks_"),
        "servers": {"SIM": {"host": "127.0.0.1", "port": 8002, "params": {}}},
    }

    class _Stub:
        def meta_writer_for(self, base):
            return object()

        def __getattr__(self, name):
            raise AssertionError(f"port member {name!r} used during construction")

    stub: Any = _Stub()
    wiring = PortWiring(
        config=stub,
        logging=stub,
        clock=stub,
        transport=stub,
        state_persistence=stub,
        status=stub,
        health=stub,
        artifact_store=stub,
    )
    return ActionHost(
        server_key="SIM",
        server_title="SIM",
        description="shutdown hooks test",
        version=1.0,
        driver_classes=[FailingTeardownDriver],
        wiring=wiring,
        helao_cfg=cfg,
    )


def test_shutdown_completes_when_both_driver_hooks_raise(caplog) -> None:
    from helao.hexagon.app import action_host

    host = _host()
    lg = action_host.LOGGER
    old_level = lg.level
    lg.setLevel(logging.DEBUG)
    lg.addHandler(caplog.handler)
    try:
        with TestClient(host):
            pass  # leaving the block runs the lifespan shutdown
    finally:
        lg.removeHandler(caplog.handler)
        lg.setLevel(old_level)
    assert host._shutdown_task is not None
    retvals = host._shutdown_task.result()
    assert retvals == {"shutdown": None, "async_shutdown": None}
    failed = [
        r
        for r in caplog.records
        if r.levelno == logging.ERROR
        and r.exc_info
        and "raised; continuing" in r.getMessage()
    ]
    assert len(failed) == 2
    assert host.fault_file is None  # the fault-file close still ran
