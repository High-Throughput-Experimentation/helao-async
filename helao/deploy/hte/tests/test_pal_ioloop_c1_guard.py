"""Driver-guard test for the C1 fail-loud-not-hang contract (plan Phase 4).

Run (from repo root, ``helao`` conda env, ``PYTHONPATH`` = repo root)::

    conda run -n helao python helao/deploy/hte/tests/test_pal_ioloop_c1_guard.py

C1 requires that a shim ``RuntimeError`` raised inside the PAL IO loop -- from
either the ``_PAL_IOloop_meas_start_helper`` ``get_samples`` call (pal_driver
``:2354`` region) or a per-microcam ``_sendcommand_main`` call (``:2327``
region) -- must NOT hang the action. Instead the loop must:

* catch the exception (no unhandled exception escapes ``_PAL_IOloop``),
* set a terminal ``self.IO_error`` (a non-``none`` ``ErrorCodes``),
* ALWAYS run ``_PAL_IOloop_meas_end_helper`` (the ``finally``), and
* stamp the finalized action with the terminal ``error_code`` (NOT
  ``ErrorCodes.none`` -- otherwise a SAMPLE outage finalizes as silent
  SUCCESS).

This drives the REAL ``_PAL_IOloop`` / ``_PAL_IOloop_meas_start_helper`` /
``_PAL_IOloop_meas_end_helper`` control flow. What is mocked (and only these):

* the driver's hardware/config plumbing: the ``PAL`` instance is built with
  ``__new__`` and the loop-relevant attributes are set by hand (no SSH, no
  NI-DAQ, no ``Base`` server);
* the ``Active`` object (``finish_hlo_header`` / ``get_realtime`` / ``finish``
  are trivial fakes that record whether ``meas_end`` finalized the action);
* ``self.archive`` (the shim) -- stubbed to RAISE on a bookkeeping call;
* ``self._sendcommand_main`` -- stubbed for the sendcommand-path scenario.

Reverting the C1 edit (the inner ``try/except`` + ``finally`` + the
``meas_end`` stamp) makes this test FAIL (meas_end never runs / error_code
stays ``none``); with C1 it PASSES.
"""

import asyncio
from types import SimpleNamespace

from helao.core.error import ErrorCodes
from helao.deploy.hte.drivers.robot.enum import Spacingmethod
from helao.deploy.hte.drivers.robot.pal_driver import PAL


class _FakeAction:
    def __init__(self):
        self.error_code = ErrorCodes.none
        self.action_uuid = "test-uuid"
        self.file_conn_keys = []

    def as_dict(self):
        return {}


class _FakeActive:
    """Records finalization + the error_code stamped at finish time."""

    def __init__(self):
        self.action = _FakeAction()
        self.finished = False
        self.error_code_at_finish = None

    def finish_hlo_header(self, file_conn_keys=None, realtime=None):
        return None

    async def get_realtime(self):
        return 0.0

    async def finish(self):
        self.finished = True
        self.error_code_at_finish = self.action.error_code
        return {}


class _PalCamStub:
    def __init__(self):
        self.totalruns = 1
        self.sampleperiod = []
        self.spacingmethod = Spacingmethod.linear
        self.spacingfactor = 1.0
        self.timeoffset = 0.0
        self.samples_in = []
        self.samples_out = []
        self.microcams = []
        self.cur_run = 0


def _make_pal():
    pal = PAL.__new__(PAL)  # bypass __init__ (no hardware / Base needed)
    pal.IOloop_run = True
    pal.IO_signalq = asyncio.Queue()
    pal.IO_do_meas = False
    pal.IO_measuring = True
    pal.IO_continue = False
    pal.IO_error = ErrorCodes.none
    pal.IO_trigger_task = None
    pal.IO_action_run_counter = 0
    pal.PAL_pid = None
    pal.IO_palcam = _PalCamStub()
    pal.action = _FakeAction()
    pal.active = _FakeActive()
    pal.base = SimpleNamespace(
        actionservermodel=SimpleNamespace(estop=False)
    )
    return pal


async def _drive_one_measurement(pal, timeout=5.0):
    """Run the real IO loop for exactly one queued measurement, then stop.

    Returns nothing; asserts no exception escapes the loop task.
    """
    task = asyncio.create_task(pal._PAL_IOloop())
    await asyncio.sleep(0)  # let the loop reach IO_signalq.get()
    await pal.IO_signalq.put(True)

    # Wait until meas_end finalized the action (active reset to None).
    deadline = asyncio.get_event_loop().time() + timeout
    while pal.active is not None:
        if asyncio.get_event_loop().time() > deadline:
            break
        await asyncio.sleep(0.02)

    # Loop is now blocked on the next get(); cancel cleanly.
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    # (a) no unhandled exception escaped: create_task would have stored it and
    # task.result() would re-raise; a CancelledError is expected/handled above.
    if not task.cancelled() and task.exception() is not None:
        raise AssertionError(
            f"unhandled exception escaped _PAL_IOloop: {task.exception()!r}"
        )


def _assert_terminal(pal, active, scenario):
    assert isinstance(pal.IO_error, ErrorCodes), (
        f"[{scenario}] IO_error not ErrorCodes: {type(pal.IO_error)}"
    )
    assert pal.IO_error is not ErrorCodes.none, (
        f"[{scenario}] IO_error must be non-none terminal code, got {pal.IO_error!r}"
    )
    assert active.finished, (
        f"[{scenario}] meas_end_helper did NOT finalize the action (hang bug)"
    )
    assert active.error_code_at_finish is not None, (
        f"[{scenario}] action never finalized"
    )
    assert active.error_code_at_finish is not ErrorCodes.none, (
        f"[{scenario}] finalized error_code is none -> SILENT SUCCESS on outage; "
        f"got {active.error_code_at_finish!r}"
    )


async def _scenario_meas_start_raise():
    """:2354 path -- unified_db.get_samples raises inside meas_start_helper."""
    pal = _make_pal()
    active = pal.active

    class _RaisingUnifiedDB:
        async def get_samples(self, *a, **k):
            raise RuntimeError("SAMPLE get_samples failed: simulated outage")

    pal.archive = SimpleNamespace(unified_db=_RaisingUnifiedDB())
    # _sendcommand_main should never be reached in this scenario.
    reached = {"sendcommand": False}

    async def _sc(_):
        reached["sendcommand"] = True
        return ErrorCodes.none

    pal._sendcommand_main = _sc

    await _drive_one_measurement(pal)
    assert not reached["sendcommand"], (
        "meas_start raise should short-circuit before _sendcommand_main"
    )
    _assert_terminal(pal, active, "meas_start")
    print("PASS: meas_start (:2354) raise -> terminal error_code, meas_end ran")


async def _scenario_sendcommand_raise():
    """:2327 path -- _sendcommand_main raises after a clean meas_start."""
    pal = _make_pal()
    active = pal.active

    class _OkUnifiedDB:
        async def get_samples(self, samples=None, *a, **k):
            return samples or []

    pal.archive = SimpleNamespace(unified_db=_OkUnifiedDB())

    async def _sc(_):
        raise RuntimeError("SAMPLE tray_query_sample failed: simulated outage")

    pal._sendcommand_main = _sc

    await _drive_one_measurement(pal)
    _assert_terminal(pal, active, "sendcommand")
    print("PASS: sendcommand (:2327) raise -> terminal error_code, meas_end ran")


def main():
    asyncio.run(_scenario_meas_start_raise())
    asyncio.run(_scenario_sendcommand_raise())
    print("ALL C1 DRIVER-GUARD CHECKS PASSED")


if __name__ == "__main__":
    main()
