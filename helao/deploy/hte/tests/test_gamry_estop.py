"""``GamryDriver.estop`` and the adapter that carries it to the COM thread.

A station drill found no PSTAT E-STOP evidence and no cell shutdown. The E-STOP
route calls ``self.driver.estop``; on the PSTAT server that driver is
``GamryComAdapter``, which owns a COM worker thread, so the adapter marshals the
call onto that thread (as it does for ``stop``) and the legacy driver makes the
same two calls ``cleanup()`` makes: ``SetCell(CellOff)`` and ``SetDigitalOut``
clearing each TTL line. Release is a no-op: it never turns the cell back on.

``comtypes`` is Windows-only, so the pstat is a recorder and the COM thread has
its COM hooks stubbed, as in ``helao/hexagon/tests/test_gamry_com.py``.
"""

import threading

import pytest
from starlette.testclient import TestClient

from helao.deploy.hte.drivers.pstat.gamry.device import TTL_OFF
from helao.deploy.hte.drivers.pstat.gamry.driver import GamryDriver
from helao.helpers.dispatcher import _query_safe
from helao.helpers.premodels import Action
from helao.hexagon.adapters.native.gamry_com import GamryComAdapter, GamryComThread

CELL_OFF = object()
_CELL_OFF_CALL = ("SetCell", (CELL_OFF,))
_TTL_CALLS = [("SetDigitalOut", tuple(TTL_OFF[k])) for k in TTL_OFF]


class FakePstat:
    def __init__(self):
        self.calls: list[tuple] = []
        self.threads: list[int] = []
        self.fail: set = set()

    def _rec(self, name, args):
        self.calls.append((name, args))
        self.threads.append(threading.get_ident())
        if name in self.fail:
            raise RuntimeError(f"{name} failed")

    def SetCell(self, *args):
        self._rec("SetCell", args)

    def SetDigitalOut(self, *args):
        self._rec("SetDigitalOut", args)

    def __getattr__(self, name):
        # any other COM call (MeasureV, DigitalIn, ...) is recorded so a test can
        # prove the estop made none.
        return lambda *args: self._rec(name, args)


class StubComThread(GamryComThread):
    def _com_initialize(self):
        pass

    def _com_pump(self, timeout_s):
        pass


def _driver(pstat):
    d = GamryDriver.__new__(GamryDriver)  # no COM: connect() is Windows-only
    d.pstat = pstat
    d.GamryCOM = type("GamryCOM", (), {"CellOff": CELL_OFF})
    return d


@pytest.fixture
def pstat():
    return FakePstat()


@pytest.mark.asyncio
async def test_latch_turns_the_cell_off_then_clears_every_ttl(pstat):
    assert await _driver(pstat).estop(switch=True) is True
    assert pstat.calls == [_CELL_OFF_CALL] + _TTL_CALLS


@pytest.mark.asyncio
async def test_setcell_raising_still_clears_the_ttls_and_does_not_raise(pstat):
    pstat.fail = {"SetCell"}
    assert await _driver(pstat).estop(switch=True) is True
    assert pstat.calls == [_CELL_OFF_CALL] + _TTL_CALLS


@pytest.mark.asyncio
async def test_one_ttl_raising_still_clears_the_rest(pstat):
    pstat.fail = {"SetDigitalOut"}
    assert await _driver(pstat).estop(switch=True) is True
    assert pstat.calls == [_CELL_OFF_CALL] + _TTL_CALLS  # all four were tried


@pytest.mark.asyncio
async def test_release_makes_no_calls_and_never_turns_the_cell_on(pstat):
    assert await _driver(pstat).estop(switch=False) is False
    assert pstat.calls == []


@pytest.mark.asyncio
async def test_no_pstat_is_a_safe_noop():
    assert await _driver(None).estop(switch=True) is True


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


@pytest.mark.parametrize("switch", [True, False])
def test_the_real_estop_route_reaches_the_pstat_on_the_com_thread(pstat, switch):
    """Smallest real wiring: a real ``ActionHost`` whose driver is the real
    ``GamryComAdapter`` (the class ``makeApp`` passes as ``driver_classes``) on a
    real worker thread, wrapping a ``GamryDriver`` over a recording pstat."""
    com = StubComThread()
    com.start()
    try:
        adapter = GamryComAdapter(config={})
        adapter._thread = com
        adapter._driver = _driver(pstat)
        host = _host("PSTAT")
        host.driver = adapter
        A = Action(action_name="estop", action_params={"switch": switch})
        resp = TestClient(host).post(
            "/PSTAT/estop",
            params=_query_safe({"switch": switch}),
            json={"action": A.as_dict()},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["driver"] is switch
        if switch:
            assert pstat.calls == [_CELL_OFF_CALL] + _TTL_CALLS
            com_ident = com.call(threading.get_ident)
            assert set(pstat.threads) == {com_ident}  # same thread as every COM call
        else:
            assert pstat.calls == []
    finally:
        com.stop()


@pytest.mark.asyncio
async def test_adapter_estop_when_not_connected_does_not_raise():
    assert await GamryComAdapter(config={}).estop(switch=True) is True


def test_a_route_timeout_does_not_drop_the_queued_cell_off(pstat, monkeypatch):
    """The route bounds the driver estop with ``wait_for``, which cancels the
    adapter's awaited future. If the COM thread has not started the queued item
    yet, a cancelled ``concurrent.futures.Future`` is skipped by the worker, so
    CellOff would never run. The adapter shields the wait so it still does."""
    import time

    import helao.hexagon.app.action_host as ah

    bound, busy = 0.3, 1.0  # scaled down from 2.0 s; the COM call outlasts the bound
    monkeypatch.setattr(ah, "ESTOP_DRIVER_TIMEOUT_S", bound)
    com = StubComThread()
    com.start()
    try:
        adapter = GamryComAdapter(config={})
        adapter._thread = com
        adapter._driver = _driver(pstat)
        host = _host("PSTAT")
        host.driver = adapter
        com.submit(time.sleep, busy)  # an in-flight COM call
        A = Action(action_name="estop", action_params={"switch": True})
        t0 = time.monotonic()
        resp = TestClient(host).post(
            "/PSTAT/estop",
            params=_query_safe({"switch": True}),
            json={"action": A.as_dict()},
        )
        took = time.monotonic() - t0
        assert resp.status_code == 200, resp.text
        assert resp.json()["driver"] == {"error": "timeout"}
        assert bound <= took < busy  # the route did not wait for the thread
        assert host.actionservermodel.estop is True
        deadline = time.monotonic() + busy + 2.0
        while _CELL_OFF_CALL not in pstat.calls and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pstat.calls == [_CELL_OFF_CALL] + _TTL_CALLS  # ran once the thread freed
    finally:
        com.stop()
