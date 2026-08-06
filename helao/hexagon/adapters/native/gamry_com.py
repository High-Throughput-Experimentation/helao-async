"""Gamry COM worker-thread adapter (P3a Gamry COM track — construct-test tier).

The native-cut-over seam for the hte Gamry potentiostat. GamryCOM objects have
**thread/apartment affinity**: the dtaq event sink + ``PumpEvents`` message loop
want a single owning thread, and every pstat/dtaq/readz call must happen on that
thread. This adapter gives them one.

- :class:`GamryComThread` owns a dedicated worker thread that initializes the COM
  apartment, runs an interleaved request-drain + ``PumpEvents`` loop (so both
  submitted calls and dtaq sink callbacks progress), and marshals each call's
  result/exception back through a ``concurrent.futures.Future``. The
  COM-specific bits (``_com_initialize``/``_com_pump``/``_com_finalize``) are
  isolated behind three overridable hooks so the thread/queue/Future machinery
  is testable on Linux with COM stubbed (comtypes is Windows-only).
- :class:`GamryComAdapter` is disconnected-construct (``__init__`` touches no COM,
  starts no thread — §10.4). ``connect()`` starts the thread and constructs the
  **legacy ``GamryDriver`` on that thread**, so all existing COM logic is reused
  verbatim; every verb is a thin ``submit(...)`` onto the owning thread. An
  ``_active`` strategy flag (dc/eis/idle) replaces the driver's implicit
  readz-vs-dtaqsink stop branch.

**Apartment (STA vs MTA) is deferred to at-station.** ``coinit_flags`` defaults
to ``0x0`` (``COINIT_MULTITHREADED``), matching the legacy driver — i.e. the
lower-risk "dedicated MTA worker" variant. Switching to STA
(``COINIT_APARTMENTTHREADED`` = ``0x2``) is a single constructor arg, to be
decided against observed event reliability on the bench.

**Wired as the gamry action server's driver** (``driver_classes=[GamryComAdapter]``)
after at-station validation (single-pump/no-missed-points, PEIS, golden_diff,
MTA apartment affinity — PR 205). The COM/threading behavior is not
Linux-runtime-verifiable; the Linux tests cover the marshalling + drain +
strategy machinery with COM stubbed. See
``docs/superpowers/plans/2026-07-22-P3a-gamry-com-sta-thread.md``.
"""

import queue
import sys
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any, Optional

import numpy as np

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["GamryComThread", "GamryComAdapter"]

# COM apartment models (winbase / objbase COINIT_*).
COINIT_MULTITHREADED = 0x0
COINIT_APARTMENTTHREADED = 0x2

_STOP = object()


class GamryComThread:
    """Dedicated worker thread owning the GamryCOM apartment AND the pump.

    All COM calls are marshalled here via :meth:`submit`; the loop interleaves
    draining submitted work with pumping COM messages so dtaq event-sink
    callbacks are delivered on this same (owning) thread.

    This loop is the SOLE ``PumpEvents`` caller: measurement data flows in via
    the sink callbacks it pumps, and ``GamryComAdapter.get_data`` only drains
    the sink (never pumps). Keeping one pump owner avoids the double-pump that
    delegating to the legacy ``GamryDriver.get_data`` (which pumps per call)
    would cause, and gives the dtaq sink a single, continuously-serviced thread.
    """

    def __init__(
        self,
        coinit_flags: int = COINIT_MULTITHREADED,
        pump_interval_s: float = 0.05,
    ):
        self._coinit_flags = coinit_flags
        self._pump_interval_s = pump_interval_s
        self._queue: "queue.Queue" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._init_error: Optional[BaseException] = None

    # --- COM-specific hooks (real comtypes; overridden/no-op in construct-tests)
    def _com_initialize(self) -> None:
        """Set the apartment flag and initialize COM on this thread.

        comtypes reads ``sys.coinit_flags`` when it first initializes COM on a
        thread; set it here (on the owning thread, before any COM use) so this
        thread gets the chosen apartment. The actual ``CoInitializeEx`` happens
        lazily on the first COM object creation (when the wrapped ``GamryDriver``
        is constructed on this thread).
        """
        sys.coinit_flags = self._coinit_flags  # type: ignore[attr-defined]
        import comtypes  # noqa: F401  (import here so Linux/no-comtypes stays lazy)

    def _com_pump(self, timeout_s: float) -> None:
        """Pump pending COM messages for up to ``timeout_s`` seconds."""
        import comtypes.client as client

        client.PumpEvents(timeout_s)

    def _com_finalize(self) -> None:
        """Thread-exit COM teardown (comtypes uninitializes at thread exit)."""
        return None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("GamryComThread already started")
        self._thread = threading.Thread(target=self._run, name="gamry-com", daemon=True)
        self._thread.start()
        self._ready.wait()
        if self._init_error is not None:
            err, self._init_error = self._init_error, None
            self._thread = None
            raise err

    def _run(self) -> None:
        try:
            self._com_initialize()
        except BaseException as exc:  # surface init failure to start()
            self._init_error = exc
            self._ready.set()
            return
        self._ready.set()
        try:
            while True:
                try:
                    item = self._queue.get(timeout=self._pump_interval_s)
                except queue.Empty:
                    self._safe_pump(self._pump_interval_s)
                    continue
                if item is _STOP:
                    break
                fn, args, kwargs, fut = item
                if not fut.set_running_or_notify_cancel():
                    continue
                try:
                    fut.set_result(fn(*args, **kwargs))
                except BaseException as exc:
                    fut.set_exception(exc)
                # flush any events the call generated without blocking
                self._safe_pump(0.0)
        finally:
            self._com_finalize()

    def _safe_pump(self, timeout_s: float) -> None:
        try:
            self._com_pump(timeout_s)
        except Exception:
            LOGGER.error("gamry COM pump failed", exc_info=True)

    def submit(self, fn: Callable[..., Any], *args, **kwargs) -> Future:
        """Run ``fn`` on the COM thread; return a Future for its result.

        If the thread is not running the Future is failed immediately (fail
        loud, never a silent no-op).
        """
        fut: Future = Future()
        if self._thread is None or not self._thread.is_alive():
            fut.set_exception(RuntimeError("GamryComThread is not running"))
            return fut
        self._queue.put((fn, args, kwargs, fut))
        return fut

    def call(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        """Blocking :meth:`submit` — run on the COM thread and wait for result."""
        return self.submit(fn, *args, **kwargs).result()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self, timeout_s: float = 5.0) -> None:
        if self._thread is None:
            return
        self._queue.put(_STOP)
        self._thread.join(timeout=timeout_s)
        self._thread = None


def _default_driver_factory(config: dict):
    """Construct the legacy GamryDriver (lazy import; COM happens in its ctor)."""
    from helao.deploy.hte.drivers.pstat.gamry.driver import GamryDriver

    return GamryDriver(config=config)


class GamryComAdapter(HelaoDriver):
    """Disconnected-construct wrapper that runs the legacy GamryDriver on a
    dedicated COM thread.

    Every verb marshals onto :class:`GamryComThread`; the wrapped legacy driver
    is constructed on that thread in :meth:`connect`, so all COM object creation
    and calls share one owning thread. Verb return values are the legacy
    ``DriverResponse`` objects, unchanged.

    A ``HelaoDriver`` so the gamry action server can construct it via
    ``driver_classes=[GamryComAdapter]``. The gamry-server-facing state
    (``model``/``ready``/``dtaqsink``) is exposed as read-only passthroughs to
    the wrapped driver, and the diagnostic ``pstat`` COM reads are re-exposed as
    thread-marshalled methods (``pstat_is_open``/``measure_v``/``measure_i``/
    ``measure_a``) so no COM call ever escapes the owning thread.
    """

    #: strategy currently occupying the pstat, so stop/cleanup dispatch cleanly
    #: (replaces the driver's implicit readz-vs-dtaqsink branch): one of
    #: ``"dc"``, ``"eis"``, ``"idle"``, or ``None``.
    _active: Optional[str]

    def __init__(
        self,
        config: Optional[dict] = None,
        *,
        coinit_flags: int = COINIT_MULTITHREADED,
        thread_factory: Callable[..., GamryComThread] = GamryComThread,
        driver_factory: Callable[[dict], Any] = _default_driver_factory,
    ):
        # No COM, no thread, no driver here (disconnected construct, §10.4).
        super().__init__(config=config or {})
        self._config = config or {}
        self._coinit_flags = coinit_flags
        self._thread_factory = thread_factory
        self._driver_factory = driver_factory
        self._thread: Optional[GamryComThread] = None
        self._driver: Any = None
        self._active = None

    @property
    def thread(self) -> Optional[GamryComThread]:
        return self._thread

    @property
    def driver(self) -> Any:
        """The wrapped legacy driver (only valid after connect())."""
        return self._driver

    @property
    def active_strategy(self) -> Optional[str]:
        return self._active

    # --- gamry-server-facing passthroughs (plain-attr reads, not COM calls) --
    @property
    def ready(self) -> bool:
        """Legacy ``ready`` flag (the server's dyn_endpoints waits on it)."""
        return bool(getattr(self._driver, "ready", False))

    @property
    def model(self) -> Any:
        """Selected ``GamryPstat`` model (server reads ``model.ierange``);
        available after :meth:`connect`."""
        return getattr(self._driver, "model", None)

    @property
    def dtaqsink(self) -> Any:
        """Active dtaq sink (server reads ``dtaqsink.status``, a plain str)."""
        return getattr(self._driver, "dtaqsink", None)

    @property
    def pstat(self) -> Any:
        """The wrapped driver's GamryCOM pstat object.

        Exposed so the executors/diagnostic endpoints keep calling
        ``driver.pstat.<M>()`` (DigitalIn TTL wait, MeasureV/I/A, measure_ocv).
        Under the default MTA apartment (``coinit_flags=0x0``) COM marshals
        these cross-thread calls automatically, so calling from the event-loop
        thread is safe (validated at-station, PR 205 — no RPC_E_WRONG_THREAD).
        NOTE: if ever switched to STA (``0x2``), these raw off-thread calls
        would need routing through ``thread.submit`` instead.
        """
        return getattr(self._driver, "pstat", None)

    @property
    def GamryCOM(self) -> Any:
        """The wrapped driver's GamryCOM type-library handle (see :attr:`pstat`)."""
        return getattr(self._driver, "GamryCOM", None)

    def _require_thread(self) -> GamryComThread:
        if self._thread is None or not self._thread.running:
            raise RuntimeError("GamryComAdapter is not connected")
        return self._thread

    # --- lifecycle --------------------------------------------------------
    def connect(self):
        """Start the COM thread and construct the legacy driver on it."""
        if self._thread is None:
            self._thread = self._thread_factory(coinit_flags=self._coinit_flags)
            self._thread.start()
        self._driver = self._thread.call(self._driver_factory, self._config)
        # GamryDriver.__init__ already runs connect(); return its live status.
        return self._thread.call(self._driver.get_status)

    def get_status(self):
        return self._require_thread().call(self._driver.get_status)

    def get_gamry_state(self) -> dict:
        return self._require_thread().call(self._driver.get_gamry_state)

    # --- DC / dtaq-sink strategy -----------------------------------------
    def setup(self, *args, **kwargs):
        resp = self._require_thread().call(self._driver.setup, *args, **kwargs)
        self._active = "dc"
        return resp

    def measure(self, *args, **kwargs):
        return self._require_thread().call(self._driver.measure, *args, **kwargs)

    def get_data(self, *args, **kwargs):
        """Drain newly-acquired dtaq points WITHOUT pumping COM events.

        Single-pump ownership (the deepening): the GamryComThread's loop is the
        sole ``PumpEvents`` caller, so dtaq sink callbacks are delivered
        continuously on the owning thread. This drains the sink only — unlike
        the legacy ``GamryDriver.get_data``, which calls
        ``comtypes.client.PumpEvents(pump_rate)`` itself; delegating to it would
        double-pump (loop + per-call). ``pump_rate`` args are accepted for
        signature parity and ignored.
        """
        return self._require_thread().call(self._drain)

    def _drain(self) -> DriverResponse:
        """Snapshot the dtaq sink delta (runs on the COM thread; no pump).

        Replicates the drain half of the legacy ``GamryDriver.get_data``
        (points slice -> per-output-key columns, busy/ok status, counter
        advance) minus the ``PumpEvents`` call.
        """
        driver = self._driver
        sink = driver.dtaqsink
        total = len(sink.acquired_points)
        if driver.counter < total:
            new_data = sink.acquired_points[driver.counter : total]
            data_dict = {
                k: v
                for k, v in zip(
                    driver.technique.dtaq.output_keys,
                    np.matrix(new_data).T.tolist(),
                )
            }
        else:
            data_dict = {}
        sink_state = sink.status
        if sink_state == "measuring" or driver.counter < total:
            status = DriverStatus.busy
        else:
            status = DriverStatus.ok
        driver.counter = total
        return DriverResponse(
            response=DriverResponseType.success,
            message=sink_state,
            data=data_dict,
            status=status,
        )

    # --- EIS / ReadZ strategy --------------------------------------------
    def setup_eis(self, *args, **kwargs):
        resp = self._require_thread().call(self._driver.setup_eis, *args, **kwargs)
        self._active = "eis"
        return resp

    def close_eis(self, *args, **kwargs):
        resp = self._require_thread().call(self._driver.close_eis, *args, **kwargs)
        self._active = None
        return resp

    # --- idle poll --------------------------------------------------------
    def poll(self):
        """Sample V/I/A on the COM thread (idle-only; guarded by _active)."""
        thread = self._require_thread()
        self._active = "idle"
        try:
            return thread.call(self._driver.get_status)
        finally:
            self._active = None

    # --- stop / teardown --------------------------------------------------
    async def stop(self):
        """Abort the active measurement on the owning COM thread.

        The legacy ``GamryDriver.stop`` is a coroutine (its EIS path awaits
        ``ReadZ.stop``); it is run to completion on the COM thread via a nested
        ``asyncio.run`` (a fresh loop on the *worker* thread, so the COM calls
        keep their thread affinity and no loop is nested on the caller). The
        caller awaits the cross-thread ``Future`` via ``wrap_future`` rather
        than blocking its own event loop on ``.result()``.
        """
        import asyncio

        fut = self._require_thread().submit(lambda: asyncio.run(self._driver.stop()))
        return await asyncio.wrap_future(fut)

    def cleanup(self, *args, **kwargs):
        resp = self._require_thread().call(self._driver.cleanup, *args, **kwargs)
        self._active = None
        return resp

    def disconnect(self):
        return self._require_thread().call(self._driver.disconnect)

    # --- supervisor (out-of-process; not thread-affine) -------------------
    def kill_gamrycom(self):
        """Terminate the GamryCOM OS process (psutil, no COM affinity needed)."""
        if (
            self._driver is not None
            and self._thread is not None
            and self._thread.running
        ):
            return self._thread.call(self._driver.kill_gamrycom)
        # Before connect() / after shutdown: psutil kill without an owning thread.
        return self._bare_kill()

    def reset(self):
        """Tear down the COM thread, kill GamryCOM, rebuild the thread+driver."""
        self.shutdown()
        self._bare_kill()
        return self.connect()

    def shutdown(self) -> None:
        """Cleanup + disconnect on the COM thread, then stop the thread."""
        try:
            if self._thread is not None and self._thread.running and self._driver:
                self._thread.call(self._driver.shutdown)
        except Exception:
            LOGGER.error("gamry adapter shutdown error", exc_info=True)
        finally:
            if self._thread is not None:
                self._thread.stop()
            self._thread = None
            self._driver = None
            self._active = None

    @staticmethod
    def _bare_kill():
        """psutil GamryCOM kill without an owning thread (recovery path)."""
        from helao.deploy.hte.drivers.pstat.gamry.driver import GamryDriver

        return GamryDriver.kill_gamrycom(GamryDriver.__new__(GamryDriver))
