"""GamryComThread + GamryComAdapter tests (P3a Gamry COM track, construct-test).

Linux construct-test tier ONLY. comtypes is Windows-only, so the COM-specific
hooks are stubbed: these tests prove the *thread/Future marshalling machinery*
(the novel, risky part) and the adapter's disconnected-construct + verb
delegation + strategy state — NOT real COM behavior, which is an at-station gate.
"""

import asyncio
import threading
import time

import pytest

from helao.core.drivers.helao_driver import DriverStatus

from helao.hexagon.adapters.native.gamry_com import (
    COINIT_APARTMENTTHREADED,
    COINIT_MULTITHREADED,
    GamryComAdapter,
    GamryComThread,
)


# ==========================================================================
# GamryComThread — real thread, COM hooks stubbed
# ==========================================================================
class _StubComThread(GamryComThread):
    """GamryComThread with COM replaced by counters (no comtypes)."""

    def __init__(self, coinit_flags=COINIT_MULTITHREADED, pump_interval_s=0.01):
        super().__init__(coinit_flags=coinit_flags, pump_interval_s=pump_interval_s)
        self.pump_count = 0
        self.initialized = False
        self.finalized = False
        self.init_thread_ident = None
        self.applied_coinit = None

    def _com_initialize(self):
        # record what a real _com_initialize would set, without importing comtypes
        self.applied_coinit = self._coinit_flags
        self.initialized = True
        self.init_thread_ident = threading.get_ident()

    def _com_pump(self, timeout_s):
        self.pump_count += 1

    def _com_finalize(self):
        self.finalized = True


def test_submit_runs_on_worker_thread_and_returns_result():
    t = _StubComThread()
    t.start()
    try:
        main = threading.get_ident()
        run_ident = t.call(threading.get_ident)
        assert run_ident != main
        assert run_ident == t.init_thread_ident  # COM init + calls share a thread
        assert t.call(lambda x: x + 1, 41) == 42
    finally:
        t.stop()


def test_submit_propagates_exceptions():
    t = _StubComThread()
    t.start()
    try:

        def boom():
            raise ValueError("com blew up")

        with pytest.raises(ValueError, match="com blew up"):
            t.call(boom)
    finally:
        t.stop()


def test_submit_before_start_fails_loud():
    t = _StubComThread()
    fut = t.submit(lambda: 1)
    with pytest.raises(RuntimeError, match="not running"):
        fut.result()


def test_calls_are_ordered_fifo():
    t = _StubComThread()
    t.start()
    try:
        seen = []
        futs = [t.submit(seen.append, i) for i in range(20)]
        for f in futs:
            f.result()
        assert seen == list(range(20))
    finally:
        t.stop()


def test_pump_runs_after_calls_and_while_idle():
    t = _StubComThread(pump_interval_s=0.005)
    t.start()
    try:
        t.call(lambda: None)
        assert t.pump_count >= 1  # after-call flush pump
        before = t.pump_count
        time.sleep(0.05)
        assert t.pump_count > before  # idle loop keeps pumping (liveness)
    finally:
        t.stop()


def test_init_failure_surfaces_to_start():
    class _BadInit(_StubComThread):
        def _com_initialize(self):
            raise OSError("no COM here")

    t = _BadInit()
    with pytest.raises(OSError, match="no COM here"):
        t.start()
    assert t.running is False  # thread reference cleared on failed start


def test_apartment_flag_is_applied_on_the_thread():
    t = _StubComThread(coinit_flags=COINIT_APARTMENTTHREADED)
    t.start()
    try:
        assert t.applied_coinit == COINIT_APARTMENTTHREADED
    finally:
        t.stop()


def test_stop_joins_and_finalizes():
    t = _StubComThread()
    t.start()
    assert t.running is True
    t.stop()
    assert t.running is False
    assert t.finalized is True


def test_double_start_raises():
    t = _StubComThread()
    t.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            t.start()
    finally:
        t.stop()


# ==========================================================================
# GamryComAdapter — fake inline thread + fake driver (no COM, no real thread)
# ==========================================================================
class _InlineThread(GamryComThread):
    """Thread stand-in that runs submitted callables inline (deterministic).

    Subclasses GamryComThread so it satisfies the adapter's thread_factory type
    without spawning a real thread; every method is overridden to run inline.
    """

    def __init__(self, coinit_flags=COINIT_MULTITHREADED):
        super().__init__(coinit_flags=coinit_flags)
        self.coinit_flags = coinit_flags
        self._running = False
        self.stopped = False

    def start(self):
        self._running = True

    def call(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def submit(self, fn, *args, **kwargs):  # unused by adapter verbs but part of API
        from concurrent.futures import Future

        fut: Future = Future()
        fut.set_result(fn(*args, **kwargs))
        return fut

    @property
    def running(self):
        return self._running

    def stop(self, timeout_s=5.0):
        self._running = False
        self.stopped = True


class _FakeSink:
    """dtaq event sink stand-in (points arrive via the thread pump)."""

    def __init__(self):
        self.acquired_points: list = []
        self.status = "measuring"


class _FakeDtaq:
    def __init__(self, output_keys):
        self.output_keys = output_keys


class _FakeTechnique:
    def __init__(self, output_keys):
        self.dtaq = _FakeDtaq(output_keys)


class _FakeGamry:
    def __init__(self, config):
        self.config = config
        self.calls = []
        # drain surface (single-pump get_data reads these; never calls get_data)
        self.counter = 0
        self.dtaqsink = _FakeSink()
        self.technique = _FakeTechnique(["t_s", "Ewe_V"])

    def get_status(self):
        self.calls.append("get_status")
        return "STATUS"

    def get_gamry_state(self):
        return {"state": "idle"}

    def setup(self, *a, **k):
        self.calls.append("setup")
        return "SETUP"

    def measure(self, *a, **k):
        self.calls.append("measure")
        return "MEASURE"

    def get_data(self, *a, **k):
        # Must NOT be called by the adapter (single-pump: adapter drains the
        # sink itself). Recorded so a test can assert it's never invoked.
        self.calls.append("get_data")
        return "DELEGATED_GET_DATA"

    def setup_eis(self, *a, **k):
        self.calls.append("setup_eis")
        return "EIS"

    def close_eis(self, *a, **k):
        self.calls.append("close_eis")
        return "CLOSE_EIS"

    def cleanup(self, *a, **k):
        self.calls.append("cleanup")
        return "CLEANUP"

    def disconnect(self):
        self.calls.append("disconnect")
        return "DISCONNECT"

    async def stop(self):
        self.calls.append("stop")
        return "STOP"

    def shutdown(self):
        self.calls.append("shutdown")

    def kill_gamrycom(self):
        self.calls.append("kill_gamrycom")
        return "KILLED"


def _adapter():
    made = {}

    def thread_factory(coinit_flags=COINIT_MULTITHREADED):
        t = _InlineThread(coinit_flags=coinit_flags)
        made["thread"] = t
        return t

    def driver_factory(config):
        d = _FakeGamry(config)
        made["driver"] = d
        return d

    a = GamryComAdapter(
        {"dev_id": 0},
        thread_factory=thread_factory,
        driver_factory=driver_factory,
    )
    return a, made


def test_disconnected_construct_touches_nothing():
    a, made = _adapter()
    assert a.thread is None
    assert a.driver is None
    assert a.active_strategy is None
    assert made == {}  # neither thread nor driver constructed at __init__


def test_verbs_before_connect_fail_loud():
    a, _ = _adapter()
    with pytest.raises(RuntimeError, match="not connected"):
        a.get_status()


def test_connect_starts_thread_and_builds_driver_on_it():
    a, made = _adapter()
    status = a.connect()
    assert a.thread is made["thread"]
    assert made["thread"].running is True
    assert a.driver is made["driver"]
    assert status == "STATUS"


def test_verbs_delegate_and_track_strategy():
    a, made = _adapter()
    a.connect()
    d = made["driver"]

    assert a.setup(technique="OCV") == "SETUP"
    assert a.active_strategy == "dc"
    assert a.measure() == "MEASURE"

    assert a.cleanup() == "CLEANUP"
    assert a.active_strategy is None

    assert a.setup_eis() == "EIS"
    assert a.active_strategy == "eis"
    assert a.close_eis() == "CLOSE_EIS"
    assert a.active_strategy is None

    assert a.poll() == "STATUS"
    assert a.active_strategy is None  # idle poll resets after sampling

    assert "setup" in d.calls and "setup_eis" in d.calls


def test_get_data_drains_sink_without_delegating_or_pumping():
    # single-pump ownership: get_data drains the sink itself and must NOT call
    # the legacy driver.get_data (where the per-call PumpEvents lives).
    a, made = _adapter()
    a.connect()
    d = made["driver"]
    d.dtaqsink.acquired_points = [[1.0, 2.0], [3.0, 4.0]]
    d.dtaqsink.status = "measuring"

    resp = a.get_data(0.1)  # pump_rate arg accepted + ignored
    assert resp.data == {"t_s": [1.0, 3.0], "Ewe_V": [2.0, 4.0]}
    assert resp.status == DriverStatus.busy  # still measuring
    assert d.counter == 2  # advanced
    assert "get_data" not in d.calls  # never delegated (no double-pump)


def test_get_data_incremental_then_done():
    a, made = _adapter()
    a.connect()
    d = made["driver"]
    d.dtaqsink.acquired_points = [[1.0, 2.0]]
    a.get_data()
    # more points arrive (delivered by the thread pump, simulated here)
    d.dtaqsink.acquired_points.append([3.0, 4.0])
    resp = a.get_data()
    assert resp.data == {"t_s": [3.0], "Ewe_V": [4.0]}  # only the new point
    # measurement finishes, all drained -> ok + empty delta
    d.dtaqsink.status = "done"
    resp2 = a.get_data()
    assert resp2.data == {}
    assert resp2.status == DriverStatus.ok


def test_stop_runs_driver_coroutine_on_thread():
    # Uses a REAL worker thread (stubbed COM) so the driver's stop coroutine
    # runs via asyncio.run on the worker thread — not nested on the caller's
    # loop. The inline fake thread can't model this (single-thread collapse).
    made = {}

    def thread_factory(coinit_flags=COINIT_MULTITHREADED):
        made["thread"] = _StubComThread(coinit_flags=coinit_flags)
        return made["thread"]

    def driver_factory(config):
        made["driver"] = _FakeGamry(config)
        return made["driver"]

    a = GamryComAdapter(
        {}, thread_factory=thread_factory, driver_factory=driver_factory
    )
    a.connect()
    try:
        assert asyncio.run(a.stop()) == "STOP"
        assert "stop" in made["driver"].calls
    finally:
        a.shutdown()


def test_shutdown_cleans_and_stops_thread():
    a, made = _adapter()
    a.connect()
    thread = made["thread"]
    a.shutdown()
    assert "shutdown" in made["driver"].calls
    assert thread.stopped is True
    assert a.thread is None and a.driver is None and a.active_strategy is None


def test_coinit_flag_forwarded_to_thread():
    a, made = _adapter()
    a._coinit_flags = COINIT_APARTMENTTHREADED
    a.connect()
    assert made["thread"].coinit_flags == COINIT_APARTMENTTHREADED
