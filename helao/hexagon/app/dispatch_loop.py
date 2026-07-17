"""Single-drainer dispatch loop + legacy-Orch graft (spec §4.5, KEEP #2/#3).

ONE long-lived asyncio task parked on an Event owns every queue-draining
command (DispatchHeadAction / FinishThenDispatch* / CloseOut* arise only
from LoopIterate, which only this task feeds): double-drain (F2b) is
structurally impossible. Control events run at their trigger site through
the same pure reducer (DD-3): E-STOP is concurrent with the loop exactly as
legacy's ingester-task estop_loop is, and the marked commands' live
re-checks are the race guard. In-process self-ops (KEEP #3): nothing here
ever dispatches an RPC/HTTP request to its own server — every effect is a
direct method call on the wrapped legacy Orch."""

import asyncio
from dataclasses import dataclass, field, replace
from typing import Callable, Dict

from helao.hexagon.app.orch_effects import (
    _LazyServerLogger,
    OrchCommandRunner,
    apply_state_delta,
    derive_state,
)
from helao.hexagon.app.wiring import PortWiring
from helao.hexagon.domain.dispatch_policy import DispatchPolicy, ExitLoop
from helao.hexagon.domain.models import ErrorCodes, LoopStatus
from helao.hexagon.domain.orchestration import (
    ClearErrorRequested,
    ClearEstopRequested,
    CreateDispatchLoopTask,
    EstopRequested,
    Event,
    LoopIterate,
    RetryDriverHealth,
    SkipRequested,
    StartRequested,
    StopRequested,
    UncaughtLoopException,
    WaitAllActionsIdle,
    step,
)

LOGGER = _LazyServerLogger()  # see orch_effects.py for the call-time-resolution
_POLICY = DispatchPolicy()

__all__ = ["HexDispatchLoop", "HexRuntime", "HexagonGraft", "graft_hexagon_loop"]


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
                await self.effects.execute(cmd)
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


@dataclass
class HexagonGraft:
    runtime: HexRuntime
    loop: HexDispatchLoop
    effects: OrchCommandRunner
    originals: Dict[str, Callable] = field(default_factory=dict)

    async def close(self) -> None:
        await self.loop.close()


def graft_hexagon_loop(orch, wiring: PortWiring) -> HexagonGraft:
    """Rebind the legacy Orch's control methods onto the reducer runtime and
    start the single-drainer loop. Instance-level rebinding is the sanctioned
    wrap seam (orch_estop.py docstring: instance patches stay observable);
    NO legacy source is modified."""
    effects = OrchCommandRunner(orch, wiring)
    runtime = HexRuntime(orch, effects)
    loop = HexDispatchLoop(runtime)
    graft = HexagonGraft(runtime=runtime, loop=loop, effects=effects)
    for name in (
        "start",
        "start_loop",
        "stop",
        "skip",
        "estop_loop",
        "clear_estop",
        "clear_error",
    ):
        graft.originals[name] = getattr(orch, name)

    async def hex_start():
        await runtime.handle(StartRequested())
        orch.current_stop_message = ""  # legacy start() clears the banner

    async def hex_start_loop():
        await runtime.handle(StartRequested())
        return orch.globalstatusmodel.loop_state

    async def hex_stop(reset_run_id: bool = False):
        # guard structure mirrors orch.py:541-556 verbatim
        if orch.globalstatusmodel.loop_state == LoopStatus.started:
            await runtime.handle(StopRequested())
        elif orch.globalstatusmodel.loop_state == LoopStatus.estopped:
            LOGGER.info("orchestrator E-STOP flag was raised; nothing to stop")
        else:
            LOGGER.info("orchestrator is not running")
        if reset_run_id:
            LOGGER.info("resetting active_run_id on stop")
            orch.active_run_id = None

    async def hex_skip():
        # mirrors orch.py:528-534
        if orch.globalstatusmodel.loop_state == LoopStatus.started:
            await runtime.handle(SkipRequested())
        else:
            LOGGER.info("orchestrator not running, clearing action queue")
            orch.action_dq.clear()

    async def hex_estop_loop(reason: str = ""):
        # legacy estop_loop message shape ("E-STOP" + optional suffix);
        # cascade runs HERE at the trigger site through the reducer (DD-3)
        msg = f"E-STOP{' ' + reason if reason else ''}"
        await runtime.handle(EstopRequested(reason=msg))
        # legacy estop_loop's intend_none() wakes the interrupt queue; the
        # reducer's none->none intent delta skips that call, so wake
        # explicitly (a dispatch effect parked in wait_for_interrupt must
        # re-check and observe the estop) — DD-5 item 6
        await orch.interrupt_q.put("estop")

    async def hex_clear_estop():
        await runtime.handle(ClearEstopRequested())

    async def hex_clear_error():
        await runtime.handle(ClearErrorRequested())

    orch.start = hex_start
    orch.start_loop = hex_start_loop
    orch.stop = hex_stop
    orch.skip = hex_skip
    orch.estop_loop = hex_estop_loop
    orch.clear_estop = hex_clear_estop
    orch.clear_error = hex_clear_error
    loop.start()
    return graft
