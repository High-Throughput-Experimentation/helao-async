"""Short-lived in-process micro-orchestrator.

:class:`MicroOrch` builds an :class:`~helao.framework.domain.orchestration.OrchState`,
enqueues work, and drives it to completion by **reusing the same**
:class:`~helao.framework.app.orch_api.OrchDriver` — so the dispatch loop, the
FSM, and the command-execution glue are exactly the ones the long-lived
orchestrator app uses. The only difference is composition: no FastAPI server,
caller-supplied ports (default to in-memory fakes), and a synchronous
``run_*`` entry point.

This is the framework replacement for ``helao.core.runners.micro_orch`` (1105
LOC of bespoke HTTP dispatch); the dispatch logic now lives once, in the pure
FSM + the shared ``execute_commands`` glue.
"""
from __future__ import annotations

import asyncio
import tempfile
from typing import Callable, Mapping, Optional

from helao.framework.adapters.fakes.transport import FakeTransport
from helao.framework.adapters.fs_storage import FsStorage
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.app.orch_api import OrchDriver, OrchPorts
from helao.framework.domain.orchestration import OrchState
from helao.framework.domain.run_models import RunAction, RunExperiment, RunSequence
from helao.framework.models.action import ActionModel
from helao.framework.ports.transport import Transport

__all__ = ["MicroOrch", "run_sequence", "run_experiment", "run_action"]


class MicroOrch:
    """An in-process orchestrator wrapping a single :class:`OrchDriver`.

    Attributes:
        driver: The :class:`OrchDriver` driving the shared FSM.
        ports: The :class:`OrchPorts` bundle the driver executes through.
    """

    def __init__(
        self,
        *,
        sequence_lib: Optional[Mapping[str, Callable]] = None,
        experiment_lib: Optional[Mapping[str, Callable]] = None,
        transport: Optional[Transport] = None,
        save_root: Optional[str] = None,
        postprocessors=None,
        state: Optional[OrchState] = None,
        server_key: str = "micro_orch",
    ) -> None:
        """Compose a micro-orchestrator from (mostly fake) ports + library maps.

        Args:
            sequence_lib: Sequence name -> factory (returns experiments).
            experiment_lib: Experiment name -> factory (returns actions).
            transport: Transport adapter; a :class:`FakeTransport` (every
                dispatch succeeds) when omitted.
            save_root: Storage root; a temp dir when omitted.
            postprocessors: HLO post-processor names.
            state: Pre-seeded :class:`OrchState`; a fresh one when omitted.
            server_key: Identifier stamped on the driver.
        """
        if save_root is None:
            save_root = tempfile.mkdtemp(prefix="helao_micro_orch_")
        self.ports = OrchPorts(
            transport=transport if transport is not None else FakeTransport(),
            storage=FsStorage(save_root=save_root),
            eventsink=QueueEventSink(),
            clock=NtpClock(),
            sequence_lib=sequence_lib,
            experiment_lib=experiment_lib,
            postprocessors=postprocessors,
        )
        self.driver = OrchDriver(server_key, ports=self.ports, state=state)

    @property
    def state(self) -> OrchState:
        """The driver's live :class:`OrchState`."""
        return self.driver.state

    async def run_sequence(self, sequence: RunSequence) -> OrchState:
        """Enqueue ``sequence`` and drive it to completion in-process."""
        self.driver.enqueue_sequence(sequence)
        await self.driver.start()
        return self.driver.state

    async def run_experiment(self, experiment: RunExperiment) -> OrchState:
        """Enqueue ``experiment`` and drive it to completion in-process."""
        self.driver.enqueue_experiment(experiment)
        await self.driver.start()
        return self.driver.state

    async def run_action(self, action) -> OrchState:
        """Stage a single ``action`` and drive it to completion in-process.

        Accepts either :class:`RunAction` or :class:`ActionModel` (the latter
        is coerced to ``RunAction`` for compat with deployment runner scripts).
        """
        if isinstance(action, ActionModel) and not isinstance(action, RunAction):
            action = RunAction(**action.model_dump())
        self.driver.state.action_dq.append(action)
        await self.driver.start()
        return self.driver.state


# --- synchronous convenience entry points ----------------------------------


def run_sequence(
    sequence: RunSequence,
    *,
    sequence_lib: Optional[Mapping[str, Callable]] = None,
    experiment_lib: Optional[Mapping[str, Callable]] = None,
    transport: Optional[Transport] = None,
    save_root: Optional[str] = None,
) -> OrchState:
    """Build a :class:`MicroOrch` and run ``sequence`` to completion (sync)."""
    micro = MicroOrch(
        sequence_lib=sequence_lib,
        experiment_lib=experiment_lib,
        transport=transport,
        save_root=save_root,
    )
    return asyncio.run(micro.run_sequence(sequence))


def run_experiment(
    experiment: RunExperiment,
    *,
    experiment_lib: Optional[Mapping[str, Callable]] = None,
    transport: Optional[Transport] = None,
    save_root: Optional[str] = None,
) -> OrchState:
    """Build a :class:`MicroOrch` and run ``experiment`` to completion (sync)."""
    micro = MicroOrch(
        experiment_lib=experiment_lib,
        transport=transport,
        save_root=save_root,
    )
    return asyncio.run(micro.run_experiment(experiment))


def run_action(
    action: RunAction,
    *,
    transport: Optional[Transport] = None,
    save_root: Optional[str] = None,
) -> OrchState:
    """Build a :class:`MicroOrch` and run a single ``action`` (sync)."""
    micro = MicroOrch(transport=transport, save_root=save_root)
    return asyncio.run(micro.run_action(action))
