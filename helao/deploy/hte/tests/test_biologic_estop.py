"""``estop`` on the three BioLogic backends (``eclib``, ``eclib2``, ``olecom``).

The E-STOP route calls ``self.driver.estop`` on the BIOLOGIC ActionHost, and the
driver there is the backend itself (``ActionHost`` builds a ``HelaoDriver`` from
``driver_classes``), so ``estop`` lives on each backend. It issues the backend's
own existing stop call for each channel that backend's ``stop()`` would stop and
nothing else: no cell-off, no reset, no disconnect. Release does nothing.

Each backend runs over its own simulator; a recorder sits at the point where a
vendor call is made (so the thread it ran on is the vendor thread) and can fail
a chosen channel. The vendor thread is a client worker (eclib, eclib2) or the
single ``olecom`` pool thread; ``estop`` has to reach it, and its wait has to be
shielded so the route's timeout cannot drop a stop that is still queued.
"""

import threading
import time
from unittest import mock
from dataclasses import dataclass, field
from typing import Callable

import pytest
from starlette.testclient import TestClient

from helao.core.drivers.helao_driver import DriverResponseType
from helao.deploy.hte.drivers.pstat.biologic import driver as eclib1_driver
from helao.deploy.hte.drivers.pstat.biologic import sim as eclib1_sim
from helao.deploy.hte.drivers.pstat.biologic import technique as bt
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import sim as ec2sim
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import technique as ec2tech
from helao.deploy.hte.drivers.pstat.biologic_eclib2.driver import (
    BiologicEclib2Driver,
)
from helao.deploy.hte.drivers.pstat.biologic_ole import technique as ot
from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver
from helao.deploy.hte.drivers.pstat.biologic_ole.sim import SimConfig, set_sim_config
from helao.helpers.dispatcher import _query_safe
from helao.helpers.premodels import Action
from helao.hexagon.tests.biologic_eclib2_sample_params import params as ec2_params

ECLIB1_CA = dict(
    Vval__V=0.5,
    Tval__s=1.0,
    AcqInterval__s=0.01,
    AcqInterval__A=10.0,
    IRange="AUTO",
    ERange="AUTO",
    Bandwidth="BW4",
)


@dataclass
class Rig:
    """A connected, set-up backend plus what it saw."""

    driver: object
    #: (channel, thread ident) per stop call that reached the vendor layer
    stops: list = field(default_factory=list)
    #: every vendor-layer call name, so a test can prove a path made none
    calls: list = field(default_factory=list)
    fail: set = field(default_factory=set)
    #: channels ``estop`` must stop: the set the backend's own ``stop()`` uses
    expected: list = field(default_factory=list)
    vendor_thread: Callable[[], int] = lambda: 0
    block: Callable[[float], None] = lambda seconds: None
    close: Callable[[], None] = lambda: None
    baseline: int = 0

    def stopped(self):
        return [ch for ch, _ in self.stops]


def _eclib1(tmp_path):
    eclib1_sim.set_sim_config(eclib1_sim.SimConfig())
    d = eclib1_driver.BiologicDriver(
        {
            "address": "192.168.200.100",
            "num_channels": 2,
            "simulate": True,
            "sdk_path": "/unused",
        }
    )
    d.connect()
    # channel 1, not 0: the claimed channel is what stop() uses, so a
    # hard-coded 0 must fail
    assert (
        d.setup(
            technique=bt.BIOTECHS["CA"], action_params={**ECLIB1_CA, "channel": 1}
        ).response
        == DriverResponseType.success
    )
    rig = Rig(driver=d, expected=[1])
    client = d._client
    real_call = client._call

    def call(name, *args):
        rig.calls.append(name)
        if name == "BL_StopChannel":
            rig.stops.append((args[1], threading.get_ident()))
            if args[1] in rig.fail:
                return -1
        return real_call(name, *args)

    client._call = call
    rig.vendor_thread = lambda: client._worker.ident
    rig.block = lambda s: threading.Thread(
        target=client._submit, args=(time.sleep, s), daemon=True
    ).start()
    rig.close = lambda: (
        d.shutdown(),
        eclib1_sim.set_sim_config(eclib1_sim.SimConfig()),
    )
    return rig


def _eclib2(tmp_path):
    d = BiologicEclib2Driver(
        {"address": "192.168.200.100", "num_channels": 2, "simulate": True}
    )
    # the simulator plugs channel 0 only; a second board makes "every channel"
    # observable
    real_info = ec2sim.DeviceInfo
    two_boards = lambda: real_info(channels_plugged=[True, True] + [False] * 14)
    with mock.patch.object(ec2sim, "DeviceInfo", two_boards):
        d.connect()
    for ch in (0, 1):
        assert (
            d.setup(
                technique=ec2tech.resolve("OCV"),
                action_params={**ec2_params("OCV"), "channel": ch},
            ).response
            == DriverResponseType.success
        )
    rig = Rig(driver=d, expected=[0, 1])
    client = d._client
    api = client._api

    def stop(handle, ch):
        api.calls.append(("BL_StopChannel", handle, ch))
        rig.stops.append((ch, threading.get_ident()))
        if ch in rig.fail:
            raise RuntimeError(f"BL_StopChannel({ch}) failed")

    api.BL_StopChannel = stop
    rig.calls = api.calls  # the simulator's own log of every vendor call
    rig.vendor_thread = lambda: client._call("ident", threading.get_ident)
    rig.block = lambda s: threading.Thread(
        target=client._call, args=("block", lambda: time.sleep(s)), daemon=True
    ).start()
    rig.close = d.shutdown
    return rig


def _ole(tmp_path):
    set_sim_config(SimConfig(run_seconds=0.0, points_per_second=100.0))
    (tmp_path / "CA.mps").write_text(
        "Technique : 1\nChronoamperometry\n"
        + "Ei (V)".ljust(20)
        + "0.000".ljust(20)
        + "\n",
        encoding="latin-1",
    )
    d = BiologicOleDriver(
        {
            "address": "192.168.200.100",
            "num_channels": 2,
            "simulate": True,
            "scratch_dir": str(tmp_path),
            "templates_dir": str(tmp_path),
        }
    )
    assert d.connect().response == DriverResponseType.success
    for ch in (0, 1):
        assert (
            d.setup(technique=ot.resolve("CA"), action_params={"channel": ch}).response
            == DriverResponseType.success
        )
    rig = Rig(driver=d, expected=[0, 1])
    client = d.client
    real_ask, real_call = client._ask, client._call

    def ask(function, *args):
        rig.calls.append(function)
        if function == "StopChannel":
            rig.stops.append((args[1], threading.get_ident()))
            if args[1] in rig.fail:
                raise RuntimeError(f"StopChannel({args[1]}) failed")
        return real_ask(function, *args)

    def call(function, *args):
        rig.calls.append(function)
        return real_call(function, *args)

    client._ask, client._call = ask, call
    rig.vendor_thread = lambda: d._pool.submit(threading.get_ident).result()
    rig.block = lambda s: d._pool.submit(time.sleep, s)
    rig.close = lambda: (d.shutdown(), set_sim_config(SimConfig()))
    return rig


BACKENDS = {"eclib": _eclib1, "eclib2": _eclib2, "olecom": _ole}


@pytest.fixture(params=list(BACKENDS))
def rig(request, tmp_path):
    r = BACKENDS[request.param](tmp_path)
    # setup() and connect() made calls of their own; only what follows counts
    r.baseline = len(r.calls)
    try:
        yield r
    finally:
        r.close()


def _name(call):
    """The simulator's log holds tuples, the other recorders hold names."""
    return call[0] if isinstance(call, tuple) else call


def _after(rig):
    return list(rig.calls[rig.baseline :])


# --- direct calls --------------------------------------------------------


@pytest.mark.asyncio
async def test_latch_stops_every_channel_the_backend_stop_uses(rig):
    assert await rig.driver.estop(switch=True) is True
    assert sorted(rig.stopped()) == rig.expected


@pytest.mark.asyncio
async def test_latch_stops_on_the_vendor_thread(rig):
    await rig.driver.estop(switch=True)
    assert rig.stops
    assert {t for _, t in rig.stops} == {rig.vendor_thread()}


@pytest.mark.asyncio
async def test_latch_makes_no_call_but_the_stops(rig):
    """No cell-off, no reset, no disconnect: only the existing stop call."""
    await rig.driver.estop(switch=True)
    names = [_name(n) for n in _after(rig)]
    assert len([n for n in names if "stop" in n.lower()]) == len(rig.expected)
    # everything else recorded after the baseline is a non-hardware-changing
    # call the stop path already makes (connection state check, info reads)
    forbidden = ("disconnect", "load", "start", "run", "setcell", "reset")
    assert not [n for n in names if any(f in n.lower() for f in forbidden)]


@pytest.mark.asyncio
async def test_one_failing_stop_does_not_skip_the_rest_or_raise(rig):
    rig.fail = {rig.expected[0]}
    assert await rig.driver.estop(switch=True) is True
    assert sorted(rig.stopped()) == rig.expected  # every channel was tried


@pytest.mark.asyncio
async def test_every_stop_failing_still_does_not_raise(rig):
    rig.fail = set(rig.expected)
    assert await rig.driver.estop(switch=True) is True
    assert sorted(rig.stopped()) == rig.expected


@pytest.mark.asyncio
async def test_release_makes_no_vendor_calls(rig):
    assert await rig.driver.estop(switch=False) is False
    assert rig.stops == []
    assert _after(rig) == []


@pytest.mark.asyncio
async def test_a_disconnected_backend_is_a_safe_noop(rig):
    rig.driver.disconnect()
    rig.stops.clear()
    assert await rig.driver.estop(switch=True) is True
    assert rig.stops == []


# --- the real route -------------------------------------------------------


def _host(key):
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
        server_key=key,
        server_title=key,
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
            "root": "/tmp",
            "servers": {key: {"host": "127.0.0.1", "port": 8002, "params": {}}},
        },
    )


def _post(host, switch):
    A = Action(action_name="estop", action_params={"switch": switch})
    return TestClient(host).post(
        "/BIOLOGIC/estop",
        params=_query_safe({"switch": switch}),
        json={"action": A.as_dict()},
    )


@pytest.mark.parametrize("switch", [True, False])
def test_the_real_estop_route_reaches_the_backend(rig, switch):
    """Smallest real wiring: a real ``ActionHost`` whose ``driver`` is the
    backend itself, which is what ``ActionHost`` puts there for a HelaoDriver."""
    host = _host("BIOLOGIC")
    host.driver = rig.driver
    resp = _post(host, switch)
    assert resp.status_code == 200, resp.text
    assert resp.json()["driver"] is switch
    if switch:
        assert sorted(rig.stopped()) == rig.expected
        assert {t for _, t in rig.stops} == {rig.vendor_thread()}
    else:
        assert rig.stops == []


def test_a_route_timeout_does_not_drop_the_queued_stop(rig, monkeypatch):
    """The route bounds ``estop`` with ``wait_for``. With the vendor worker busy
    past that bound, the stop is still queued behind it; an unshielded wait
    would cancel it. It must run once the worker frees up."""
    import helao.hexagon.app.action_host as ah

    bound, busy = 0.3, 1.0
    monkeypatch.setattr(ah, "ESTOP_DRIVER_TIMEOUT_S", bound)
    host = _host("BIOLOGIC")
    host.driver = rig.driver
    rig.block(busy)
    time.sleep(0.1)  # let the worker pick the blocker up
    t0 = time.monotonic()
    resp = _post(host, True)
    took = time.monotonic() - t0
    assert resp.status_code == 200, resp.text
    assert resp.json()["driver"] == {"error": "timeout"}
    assert bound <= took < busy  # the route did not wait for the worker
    assert host.actionservermodel.estop is True
    deadline = time.monotonic() + busy + 2.0
    while len(rig.stops) < len(rig.expected) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert sorted(rig.stopped()) == rig.expected  # ran once the worker freed
