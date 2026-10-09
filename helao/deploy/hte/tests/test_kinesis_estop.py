"""``KinesisMotor.estop``: the E-STOP must actually stop the stage.

A station drill found the KMOTOR server had no driver ``estop``, so an E-STOP
during a ``kmove`` left the stage moving. The stop is send-only
(``stop(immediate=True, sync=False)``): the same MOT_MOVE_STOP the existing
``stop()`` sends, minus the status polling that ``sync=True`` does on the shared
FTDI handle. It runs on the event-loop thread, as does everything that touches
the handle (poller ``get_data``, executor ``_exec``), so nothing is concurrent.

``Thorlabs.KinesisMotor`` is replaced by a recorder as in ``test_kinesis_counts``.
"""

import asyncio
import os
import time
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from helao.deploy.hte.drivers.motion import kinesis_driver as kd
from helao.deploy.hte.drivers.motion.kinesis_driver import KinesisMotor
from helao.helpers.dispatcher import _query_safe
from helao.helpers.premodels import Action

_AXIS = {"serial_no": "1", "pos_scale": 1228800.0, "vel_scale": 1.0, "acc_scale": 1.0}
_CFG = {"axes": {"z": dict(_AXIS), "y": dict(_AXIS, serial_no="2")}}


class FakeMotor:
    def __init__(self, conn=None, scale=None):
        self.conn = conn
        self.calls: list[tuple] = []
        self.raises = False

    def stop(self, *args, **kwargs):
        self.calls.append(("stop", args, kwargs))
        if self.raises:
            raise RuntimeError("axis unplugged")

    def __getattr__(self, name):
        # get_status / get_position / anything else: record it so a test can
        # prove it was never called.
        def _rec(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return _rec


@pytest.fixture
def driver(monkeypatch):
    monkeypatch.setattr(kd.Thorlabs, "KinesisMotor", FakeMotor)
    return KinesisMotor(config=_CFG)


_STOP = ("stop", (), {"immediate": True, "sync": False})


@pytest.mark.asyncio
async def test_latch_sends_send_only_immediate_stop_to_every_axis(driver):
    assert await driver.estop(switch=True) is True
    assert [m.calls for m in driver.motors.values()] == [[_STOP], [_STOP]]


@pytest.mark.asyncio
async def test_one_axis_raising_still_stops_the_others_and_does_not_raise(driver):
    driver.motors["z"].raises = True
    assert await driver.estop(switch=True) is True
    assert driver.motors["y"].calls == [_STOP]
    assert driver.motors["z"].calls == [_STOP]  # it was tried


@pytest.mark.asyncio
async def test_release_makes_no_calls(driver):
    assert await driver.estop(switch=False) is False
    assert [m.calls for m in driver.motors.values()] == [[], []]


@pytest.mark.asyncio
async def test_estop_reads_nothing(driver):
    await driver.estop(switch=True)
    names = {n for m in driver.motors.values() for n, _, _ in m.calls}
    assert names == {"stop"}  # no get_status / get_position / setup / close


def _host(root="/tmp"):
    from helao.hexagon.adapters.native.artifact_store import NativeArtifactStoreAdapter
    from helao.hexagon.app.action_host import ActionHost
    from helao.hexagon.app.wiring import PortWiring

    class _Clock:
        def now_ns(self):
            return 0

        def offset(self):
            return 0.0

    class _Stub:
        def __getattr__(self, name):
            raise AssertionError(f"port member {name!r} used unexpectedly")

    return ActionHost(
        server_key="KMOTOR",
        server_title="KMOTOR",
        description="estop",
        version=1.0,
        wiring=PortWiring(
            config=_Stub(),
            logging=_Stub(),
            clock=_Clock(),
            transport=_Stub(),
            state_persistence=_Stub(),
            status=_Stub(),
            health=_Stub(),
            artifact_store=NativeArtifactStoreAdapter(config=_Stub(), clock=_Clock()),
            data_sink=_Stub(),
        ),
        helao_cfg={
            "root": root,
            "servers": {"KMOTOR": {"host": "127.0.0.1", "port": 8002, "params": {}}},
        },
    )


def test_the_real_estop_route_reaches_the_motors(driver):
    """Smallest real wiring: a real ``ActionHost`` keyed ``KMOTOR`` holding the
    real driver (``ActionHost.startup`` assigns ``self.driver = drivers[0]``
    with no adapter, which is why nothing between route and driver needs one)."""
    host = _host()
    host.driver = driver
    A = Action(action_name="estop", action_params={"switch": True})
    resp = TestClient(host).post(
        "/KMOTOR/estop",
        params=_query_safe({"switch": True}),
        json={"action": A.as_dict()},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["driver"] is True
    assert host.actionservermodel.estop is True
    assert [m.calls for m in driver.motors.values()] == [[_STOP], [_STOP]]


# --------------------------------------------------------------------------
# E-STOP latch gate: no path that can move the stage runs while latched
# --------------------------------------------------------------------------
def _move_calls(driver):
    return [c for m in driver.motors.values() for c in m.calls if c[0] != "stop"]


@pytest.fixture
def gated(driver, tmp_path):
    """A real ActionHost keyed KMOTOR with the real Kinesis routes registered."""
    from helao.deploy.hte.servers.action.kinesis_server import kinesis_dyn_endpoints

    host = _host(root=str(tmp_path))
    host.server_params.update(_CFG)
    host.driver = driver
    host.poller = SimpleNamespace(
        live_dict={"z": {"position_mm": 0.0, "status": []}, "y": {}}
    )
    asyncio.run(kinesis_dyn_endpoints(host))
    with TestClient(host) as client:  # runs startup: the loop executors need
        yield host, client


def _post(client, path, action_name, params, switch=None):
    A = Action(action_name=action_name, action_params=params)
    return client.post(
        path,
        params=None if switch is None else _query_safe({"switch": switch}),
        json={"action": A.as_dict()},
    )


def _latch(client, switch):
    assert _post(client, "/KMOTOR/estop", "estop", {"switch": switch}, switch=switch)


def _kmove(client):
    return _post(client, "/KMOTOR/kmove", "kmove", {"axis": "z", "value_mm": 1.0})


def _move_axis(client):
    return client.post(
        "/move_axis", params={"axis": "z", "value": 1.0, "mode": "relative"}
    )


def test_latched_kmove_is_refused_with_no_session_and_no_move(gated, tmp_path):
    from helao.core.error import ErrorCodes

    host, client = gated
    _latch(client, True)
    resp = _kmove(client)
    assert resp.status_code == 200, resp.text
    assert resp.json()["error_code"] == ErrorCodes.estop.value
    time.sleep(0.3)  # an executor, had one started, would have moved by now
    assert _move_calls(host.driver) == []
    assert host.actives == {} and host.executors == {}
    # a rejected call creates no artifact: nothing was written under the root
    written = [f for _, _, fs in os.walk(tmp_path) for f in fs]
    assert written == ["KMOTOR_faults.txt"]  # startup's fault log, nothing else


def test_latched_move_axis_is_refused_and_sends_no_move(gated):
    from helao.core.error import ErrorCodes

    host, client = gated
    _latch(client, True)
    resp = _move_axis(client)
    assert resp.status_code == 200, resp.text
    assert resp.json()[0] == ErrorCodes.estop.value
    assert _move_calls(host.driver) == []


def test_released_kmove_proceeds_and_sends_the_move(gated):
    host, client = gated
    _latch(client, True)
    _latch(client, False)
    assert _kmove(client).status_code == 200
    deadline = time.monotonic() + 3.0
    while not _move_calls(host.driver) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert [c[0] for c in _move_calls(host.driver)] == ["move_by"]


def test_released_move_axis_sends_the_move(gated):
    from helao.core.error import ErrorCodes

    host, client = gated
    _latch(client, True)
    _latch(client, False)
    assert _move_axis(client).json()[0] == ErrorCodes.none.value
    assert [c[0] for c in _move_calls(host.driver)] == ["move_by"]


def test_stop_motion_still_works_while_latched(gated):
    host, client = gated
    _latch(client, True)
    for m in host.driver.motors.values():
        m.calls.clear()
    resp = client.post("/stop_motion")
    assert resp.status_code == 200, resp.text
    assert [m.calls for m in host.driver.motors.values()] == [
        [("stop", (), {"immediate": True, "sync": True})]
    ] * 2


def test_latch_landing_after_the_gate_stops_the_executor_before_it_moves(
    gated, monkeypatch, tmp_path
):
    """The race the entry gate cannot see: ``kmove`` passes the gate, then the
    latch lands during ``_pre_exec`` -- before the executor registers, so the
    route's executor sweep does not find it. ``_exec`` must re-check."""
    from helao.deploy.hte.servers.action.kinesis_server import KinesisMotorExec

    host, client = gated
    real_pre_exec = KinesisMotorExec._pre_exec

    async def _pre_exec_then_latch(self):
        result = await real_pre_exec(self)
        host.actionservermodel.estop = True  # the E-STOP lands here
        return result

    monkeypatch.setattr(KinesisMotorExec, "_pre_exec", _pre_exec_then_latch)
    assert _kmove(client).status_code == 200  # the gate saw no latch
    deadline = time.monotonic() + 3.0
    acts = []
    while not acts and time.monotonic() < deadline:
        time.sleep(0.05)
        acts = [
            os.path.join(d, f)
            for d, _, fs in os.walk(tmp_path)
            for f in fs
            if f.endswith("-act.yml")
        ]
    time.sleep(0.3)
    assert _move_calls(host.driver) == []
    assert acts, "the action never finished"
    assert "error_code: estop" in open(acts[0], encoding="utf-8").read()
