"""BiologicExec records the wall-clock instant of BL_StartChannel."""

import asyncio
from types import SimpleNamespace

from helao.core.drivers.helao_driver import DriverStatus
from helao.core.error import ErrorCodes
from helao.deploy.hte.servers.action.biologic_server import BiologicExec


def test_exec_writes_channel_start_epoch_s_on_success():
    ex = BiologicExec.__new__(BiologicExec)
    ex.channel = 0
    ex.ttl_params = {"ttl": "out"}
    action = SimpleNamespace(action_params={"channel": 0}, action_name="run_CV")
    ex.active = SimpleNamespace(action=action)
    ex.driver = SimpleNamespace(
        start_channel=lambda channel, ttl_params: SimpleNamespace(
            response="success",
            data={"start_time": 1234.5},
            message="measurement started",
            status=DriverStatus.busy,
        )
    )

    out = asyncio.run(ex._exec())

    assert out["error"] == ErrorCodes.none
    assert action.action_params["channel_start_epoch_s"] == 1234.5


def test_a_failed_start_does_not_record_a_start_epoch():
    ex = BiologicExec.__new__(BiologicExec)
    ex.channel = 0
    ex.ttl_params = {}
    action = SimpleNamespace(action_params={"channel": 0}, action_name="run_CV")
    ex.active = SimpleNamespace(action=action)
    ex.driver = SimpleNamespace(
        start_channel=lambda channel, ttl_params: SimpleNamespace(
            response="failed",
            data={},
            message="channel busy",
            status=DriverStatus.error,
        )
    )

    asyncio.run(ex._exec())

    assert "channel_start_epoch_s" not in action.action_params
