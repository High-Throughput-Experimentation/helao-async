"""Single-drainer dispatch loop (spec §4.5, KEEP #2/#3).

ONE long-lived asyncio task parked on an Event owns every queue-draining
command (DispatchHeadAction / FinishThenDispatch* / CloseOut* arise only
from LoopIterate, which only this task feeds): double-drain (F2b) is
structurally impossible. Control events run at their trigger site through
the same pure reducer (DD-3): E-STOP is concurrent with the loop, and the
marked commands' live re-checks are the race guard. In-process self-ops
(KEEP #3): nothing here ever dispatches an RPC/HTTP request to its own
server — every effect is a direct method call on the ``OrchHost`` that
builds this runtime (``OrchHost._build_reducer``)."""

import asyncio
from dataclasses import replace

from helao.hexagon.app.orch_effects import (
    OrchCommandRunner,
    _LazyServerLogger,
    apply_state_delta,
    derive_state,
)
from helao.hexagon.domain.dispatch_policy import DispatchPolicy, ExitLoop
from helao.hexagon.domain.models import ErrorCodes
from helao.hexagon.domain.orchestration import (
    CreateDispatchLoopTask,
    DriverHealthUnrecovered,
    Event,
    LoopIterate,
    RetryDriverHealth,
    UncaughtLoopException,
    WaitAllActionsIdle,
    step,
)

LOGGER = _LazyServerLogger()  # see orch_effects.py for the call-time-resolution
_POLICY = DispatchPolicy()

__all__ = ["HexDispatchLoop", "HexRuntime"]


class HexRuntime:
    """Pure-reducer runtime: derive live state, step, apply delta, execute."""

    def __init__(self, orch, effects: OrchCommandRunner):
        self.orch = orch
        self.effects = effects
        self.loop_wake = asyncio.Event()

    async def handle(self, event: Event) -> ErrorCodes:
        return await self._apply_and_execute(derive_state(self.orch), event)

    async def _apply_and_execute(self, old, event) -> ErrorCodes:
        new, commands = step(old, event)
        skip_loop_state = any(isinstance(c, WaitAllActionsIdle) for c in commands)
        await apply_state_delta(self.orch, old, new, skip_loop_state=skip_loop_state)
        rc = ErrorCodes.none
        for cmd in commands:
            if isinstance(cmd, CreateDispatchLoopTask):
                self.loop_wake.set()  # the long-lived task IS the loop (T1)
                continue
            if isinstance(cmd, RetryDriverHealth):
                remaining = await self.effects.execute_retry_driver_health(cmd)
                if remaining:
                    # P2a: exhaustion is now the DriverHealthUnrecovered
                    # event (reducer T12: stop intent + identical
                    # "unknown driver states: ..." stop message)
                    rc3 = await self._apply_and_execute(
                        derive_state(self.orch),
                        DriverHealthUnrecovered(na_drivers=remaining),
                    )
                    if rc3 is not ErrorCodes.none:
                        rc = rc3
                # one-shot ladder fall-through with na_drivers masked —
                # mirrors orch_dispatch._loop's non-continue driver-health
                # path (re-asking next_step with them still unknown would
                # livelock; masking == calling ladder_step directly)
                masked = replace(derive_state(self.orch), na_drivers=())
                rc2 = await self._apply_and_execute(masked, LoopIterate())
                if rc2 is not ErrorCodes.none:
                    rc = rc2
                continue
            cmd_rc = await self.effects.execute(cmd)
            if cmd_rc is not None and cmd_rc is not ErrorCodes.none:
                rc = cmd_rc
        if rc is not ErrorCodes.none:
            # legacy _loop epilogue (orch_dispatch.py:583-585)
            LOGGER.error(f"stopping orch with error code: {rc}")
            await self.orch.intend_stop()
        return rc


class HexDispatchLoop:
    """The single drainer: parked on loop_wake; sole feeder of LoopIterate."""

    def __init__(self, runtime: HexRuntime):
        self.runtime = runtime
        self._task = None
        self._closed = False

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(
            self.run_forever(), name="hexagon_dispatch_loop"
        )

    async def close(self) -> None:
        self._closed = True
        self.runtime.loop_wake.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()

    async def run_forever(self) -> None:
        while True:
            await self.runtime.loop_wake.wait()
            self.runtime.loop_wake.clear()
            if self._closed:
                return
            await self._run_started_phase()

    async def _run_started_phase(self) -> None:
        orch = self.runtime.orch
        LOGGER.info("--- started operator orch ---")  # run() :1116 wording
        LOGGER.info(f"current orch status: {orch.globalstatusmodel.orch_state}")
        try:
            while True:
                live = derive_state(orch)
                exiting = isinstance(_POLICY.next_step(live.snapshot()), ExitLoop)
                await self.runtime.handle(LoopIterate())
                if exiting:
                    # that iterate ran the reducer's finalization
                    # (close-outs + stopped-unless-estopped + export) —
                    # mirror of DispatchRunner.run's _finalize-then-return
                    return
        except Exception:
            LOGGER.error("serious orch exception occurred")
            LOGGER.error("ERROR: ", exc_info=True)
            try:  # T13: exception -> estop, like DispatchRunner.run
                await self.runtime.handle(
                    UncaughtLoopException(reason="dispatch loop exception")
                )
            except Exception:
                LOGGER.error("estop after loop exception failed", exc_info=True)
