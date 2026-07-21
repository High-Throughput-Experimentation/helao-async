"""Regression test for the PAL busy-wedge bug (CARDS P4 PAL, HIGH severity).

``_PAL_IOloop`` (pal_driver.py, ``:~2281``) used to drain the IO signal
queue directly into the busy slot::

    self._job = await self.IO_signalq.get()
    if self._job:
        ...

Since ``is_busy()`` is ``self._job is not None or self.IO_measuring``, a
drained STOP SENTINEL (``False``) left ``self._job`` set to ``False`` --
and ``False is not None`` is ``True``, so the driver reported BUSY forever
with no job in flight and nothing left to clear it. ``pal_server.py``'s
``_pal_reject_busy`` runs ``is_busy()`` BEFORE ``submit_job``, so once
wedged every subsequent PAL action is rejected ``in_progress`` permanently
(a real disconnect/reconnect is required). This is reachable via
``reset()`` (unconditionally pushes ``False``) and via ``stop()``/
``estop()`` when the ``False`` lands after the last palaction of a job.

The fix stores the drained value in a local (``signal``) and only ever
assigns a real job (or ``None``) to ``self._job``:

    signal = await self.IO_signalq.get()
    if signal:
        self._job = signal
        ...
    else:
        self._job = None

This file drives the REAL ``_PAL_IOloop`` / ``is_busy`` / ``get_status`` /
``reset`` / ``set_IO_signalq_nowait`` -- only the ``PAL`` instance is built
bare via ``__new__`` (no SSH / NI-DAQ / Base server), matching the
``test_pal_ioloop_c1_guard.py`` harness pattern.

Also includes a direct B4 busy-guard check (mirrors ``pal_server.py``'s
``_pal_reject_busy``: reject with ``ErrorCodes.in_progress`` while a real
job occupies the busy slot; pass through while idle) covering the path the
golden-master ``i_busy_rejection`` scenario stubs tautologically (it sets
``IO_measuring`` directly rather than exercising ``self._job``).

Run (conda env ``helao``, no pytest in this env -- run as a script)::

    conda run -n helao python helao/deploy/hte/tests/test_pal_busy_wedge.py
"""

import asyncio

from helao.core.drivers.helao_driver import DriverStatus
from helao.core.error import ErrorCodes
from helao.deploy.hte.drivers.robot.pal_driver import PAL, PALJob, PalCam


def _make_pal() -> PAL:
    """Bare ``PAL`` instance (bypasses ``__init__``): only the attributes the
    idle-drain path (``_PAL_IOloop``) and the busy-slot accessors
    (``is_busy``/``get_status``/``reset``/``set_IO_signalq_nowait``) touch."""
    pal = PAL.__new__(PAL)
    pal.IOloop_run = True
    pal.IO_signalq = asyncio.Queue(1)
    pal._job = None
    pal._worker_task = None
    pal.IO_measuring = False
    pal.IO_continue = False
    pal.IO_error = ErrorCodes.none
    pal.IO_action_run_counter = 0
    return pal


class _FakeAction:
    def __init__(self):
        self.error_code = ErrorCodes.none

    def as_dict(self):
        return {"error_code": self.error_code}


class _FakeActive:
    def __init__(self):
        self.action = _FakeAction()


async def _drain_idle_stop_signal(pal: PAL, push):
    """Start the real IO loop, let ``push`` enqueue a stop sentinel while the
    driver is idle, and give the loop a moment to drain it."""
    task = asyncio.create_task(pal._PAL_IOloop())
    await asyncio.sleep(0)  # let the loop reach IO_signalq.get()
    push()
    # give the loop a few ticks to actually drain and process the sentinel
    for _ in range(50):
        await asyncio.sleep(0)
        if pal.IO_signalq.empty():
            break
    await asyncio.sleep(0)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _scenario_idle_stop_sentinel_does_not_wedge():
    """Draining a raw ``False`` stop sentinel while idle must NOT wedge busy."""
    pal = _make_pal()

    assert not pal.is_busy(), "pal must start idle"

    await _drain_idle_stop_signal(pal, lambda: pal.IO_signalq.put_nowait(False))

    assert pal.is_busy() is False, (
        f"BUSY WEDGE: is_busy() returned True after draining an idle stop "
        f"sentinel (self._job={pal._job!r})"
    )
    status = pal.get_status()
    assert status.status == DriverStatus.ok, (
        f"BUSY WEDGE: get_status() reported {status.status!r} (expected "
        f"{DriverStatus.ok!r}) after draining an idle stop sentinel"
    )
    print("PASS: idle stop-sentinel drain does not wedge busy")


async def _scenario_reset_path_does_not_wedge():
    """``reset()`` unconditionally pushes a stop sentinel (``set_IO_signalq_nowait(False)``);
    once the loop drains it, the driver must be idle, not wedged busy."""
    pal = _make_pal()

    await _drain_idle_stop_signal(pal, lambda: pal.reset())

    assert pal.is_busy() is False, (
        f"BUSY WEDGE: is_busy() returned True after reset()'s stop sentinel "
        f"was drained (self._job={pal._job!r})"
    )
    status = pal.get_status()
    assert status.status == DriverStatus.ok, (
        f"BUSY WEDGE: get_status() reported {status.status!r} (expected "
        f"{DriverStatus.ok!r}) after reset()"
    )
    print("PASS: reset() path does not wedge busy")


def _pal_reject_busy(pal: PAL, action: _FakeAction):
    """Mirrors ``pal_server.py``'s ``_pal_reject_busy`` (estop/no-host checks
    omitted -- out of scope here; only the ``is_busy()`` branch matters for
    this test), run BEFORE any job/artifact would be created."""
    if pal.is_busy():
        action.error_code = ErrorCodes.in_progress
        return action.as_dict()
    return None


async def _scenario_b4_busy_guard_direct():
    """Direct test of the B4 guard: idle -> pass; real job in flight -> reject in_progress."""
    pal = _make_pal()
    action = _FakeAction()

    # -- not busy: guard must pass (return None), no rejection.
    assert pal.is_busy() is False
    rejected = _pal_reject_busy(pal, action)
    assert rejected is None, f"idle PAL must not be rejected, got {rejected!r}"

    # -- busy: a REAL job (not a bool sentinel) occupies the busy slot.
    job = PALJob(palcam=PalCam(), active=_FakeActive())
    pal._job = job
    assert pal.is_busy() is True, "a real in-flight PALJob must report busy"

    action2 = _FakeAction()
    rejected2 = _pal_reject_busy(pal, action2)
    assert rejected2 is not None, "busy PAL must reject the call"
    assert (
        rejected2["error_code"] == ErrorCodes.in_progress
    ), f"busy rejection must carry in_progress, got {rejected2['error_code']!r}"
    assert action2.error_code == ErrorCodes.in_progress

    print("PASS: B4 busy guard (idle passes, real job in flight rejects in_progress)")


def main():
    asyncio.run(_scenario_idle_stop_sentinel_does_not_wedge())
    asyncio.run(_scenario_reset_path_does_not_wedge())
    asyncio.run(_scenario_b4_busy_guard_direct())
    print("ALL PAL BUSY-WEDGE REGRESSION CHECKS PASSED")


if __name__ == "__main__":
    main()
