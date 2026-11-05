"""The DataSink port is the ten members drivers/executors use, and nothing is wired to it.

``ActionSession`` satisfies the port structurally; there is no adapter and no
``PortWiring`` slot. These tests pin the trimmed surface so a member (or a dead
slot) cannot creep back in unnoticed.
"""

import dataclasses
import inspect

import pytest

from helao.core.tests.test_active_golden_master import (
    _active_params,
    _make_host,
    _mk_action,
)
from helao.hexagon.app.action_session import ActionSession
from helao.hexagon.app.wiring import ACTION_REQUIRED, PortWiring
from helao.hexagon.ports.data_sink import DataSinkPort

PORT_MEMBERS = {
    "enqueue_data_nowait",
    "get_realtime_nowait",
    "finish_hlo_header",
    "enqueue_data",
    "write_file",
    "write_file_nowait",
    "track_file",
    "append_sample",
    "split",
    "set_estop",
}


def test_port_members_are_the_trimmed_set() -> None:
    assert {m for m in dir(DataSinkPort) if not m.startswith("_")} == PORT_MEMBERS


def test_finish_hlo_header_is_sync_on_the_port() -> None:
    assert not inspect.iscoroutinefunction(DataSinkPort.finish_hlo_header)
    assert not inspect.iscoroutinefunction(ActionSession.finish_hlo_header)


@pytest.mark.asyncio
async def test_action_session_satisfies_the_port(tmp_path) -> None:
    base = _make_host(tmp_path / "RUNS", [])
    session = ActionSession(base, _active_params(base, _mk_action("surface")))
    assert isinstance(session, DataSinkPort)
    for name in PORT_MEMBERS:
        assert inspect.iscoroutinefunction(
            getattr(session, name)
        ) == inspect.iscoroutinefunction(getattr(DataSinkPort, name)), name


def test_wiring_has_no_hardware_side_slots() -> None:
    slots = {f.name for f in dataclasses.fields(PortWiring)}
    assert not slots & {"hardware", "data_sink", "sample_state", "ui_host"}
    assert "data_sink" not in ACTION_REQUIRED
