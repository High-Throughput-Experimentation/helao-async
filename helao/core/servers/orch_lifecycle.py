"""RunLifecycle -- active-sequence/experiment close-out + wait-action dispatch
extracted from ``Orch`` (CARDS P5, Stage S6).

``Orch.finish_active_sequence``/``finish_active_experiment``/
``write_active_experiment_exp``/``write_active_sequence_seq``/``start_wait``/
``dispatch_wait_task`` implement the orchestrator's run-lifecycle cluster:
finalizing the active sequence/experiment (status transition, postprocessors,
disk write, roll-over to ``last_*``, DB move), the two small
``initial_global_params``-then-write helpers used mid-run, and the wait-action
background-task machinery. This module moves those 6 method bodies into a
``RunLifecycle`` collaborator that ``Orch`` delegates to.

Per the P5 constraints (:doc:`CARDS_REFACTOR_P5.md` sec 3.1 rule 3):
``RunLifecycle`` caches no shared mutable state -- it holds only the ``orch``
back-reference and reads/writes ``active_sequence``/``active_experiment``/
``last_sequence``/``last_experiment``/``active_seq_exp_counter``/
``globalstatusmodel``/``global_params``/``nonblocking``/``wait_task``/
``current_wait_ts``/``last_wait_ts`` through ``orch`` at call time, so a
reassignment made between construction and a call (e.g. ``import_queues``
reassigning ``active_sequence``/``active_experiment``) is always observed.
Behavior is byte-identical to the original inline methods, including
``finish_active_sequence`` calling (what was) its sibling
``write_active_sequence_seq`` -- moved here as ``self.orch.write_active_sequence_seq()``,
which correctly re-enters through the ``Orch`` delegator rather than calling
this collaborator directly (internal callers never bypass the ``Orch``
public surface).

CIRCULAR-IMPORT / MONKEYPATCH NOTE: ``orch.py`` imports this module at
module top, so ``move_dir`` is imported lazily inside
``finish_active_sequence``/``finish_active_experiment`` from
``helao.core.servers.orch`` (rather than bound once at this module's top)
-- this preserves the pre-existing external patch point
(``helao.core.servers.orch.move_dir``, e.g. the dispatch golden-master
harness's module-global rebind) exactly as it worked before extraction.
"""

import asyncio
import os
import time
from copy import deepcopy

from helao.helpers import helao_logging as logging
from helao.helpers.time_utils import set_time
from helao.core.models.hlostatus import HloStatus
from helao.core.servers.base import Active

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class RunLifecycle:
    """Active-sequence/experiment close-out and wait-action dispatch for an ``Orch``.

    Holds only the ``orch`` back-reference (never a cached attribute), per
    the call-time state resolution rule -- see module docstring.
    """

    def __init__(self, orch):
        self.orch = orch

    async def finish_active_sequence(self):
        """Finalize the active sequence: mark finished, run postprocessors, persist, and roll over."""
        orch = self.orch
        from helao.core.servers.orch import move_dir

        await orch.orch_wait_for_all_actions()
        if orch.active_sequence is not None:
            orch.active_sequence.replace_sequence_status(
                HloStatus.active, HloStatus.finished
            )
            orch.active_sequence.sequence_finished_timestamp = set_time(
                offset=orch.ntp_offset
            )
            orch.active_sequence.finished_global_params = {
                k: v for k, v in orch.global_params.items() if k != "_fast_samples_in"
            }

            # post-process experiment object
            if orch.seq_postprocessors:
                for spp, libname in zip(
                    orch.seq_postprocessors, orch.seq_postprocess_libs
                ):
                    LOGGER.info(
                        f"Running custom SEQ post-processor: {os.path.basename(libname).split('.py')[0]}"
                    )
                    loop = asyncio.get_running_loop()
                    postprocessor = spp(orch.active_sequence, orch)
                    await loop.run_in_executor(None, postprocessor.process)

            await orch.write_seq(orch.active_sequence)
            orch.last_sequence = deepcopy(orch.active_sequence)
            await orch.put_lbuf(
                {
                    orch.active_sequence.sequence_uuid: {
                        "sequence_name": orch.active_sequence.sequence_name,
                        "status": HloStatus.finished.value,
                    }
                }
            )
            orch.register_obj_uuid(
                orch.active_sequence.sequence_uuid,
                {
                    "sequence_name": orch.active_sequence.sequence_name,
                    "sequence_params": orch.active_sequence.sequence_params,
                    "sequence_timestamp": f"{orch.active_sequence.sequence_timestamp: %m-%d %H:%M:%S}",
                    "sequence_finished_timestamp": f"{orch.active_sequence.sequence_finished_timestamp: %m-%d %H:%M:%S}",
                    "sequence_status": HloStatus.finished.value,
                    "sequence_label": orch.active_sequence.sequence_label,
                    "campaign_name": (
                        orch.active_sequence.campaign_name
                        if orch.active_sequence.campaign_name
                        else None
                    ),
                },
                "sequence",
            )
            orch.active_sequence = None
            orch.active_seq_exp_counter = 0
            orch.globalstatusmodel.counter_dispatched_actions = {}
            # DB server call to finish_yml if DB exists
            orch.aloop.create_task(move_dir(orch.last_sequence, base=orch))

    async def finish_active_experiment(self):
        """Finalize the active experiment after waiting for actions and stopping non-blockers."""
        orch = self.orch
        from helao.core.servers.orch import move_dir

        # we need to wait for all actions to finish first
        await orch.orch_wait_for_all_actions()
        while len(orch.nonblocking) > 0:
            LOGGER.info(
                f"Stopping non-blocking action executors ({len(orch.nonblocking)})"
            )
            await orch.clear_nonblocking()
            await asyncio.sleep(1)
        if orch.active_experiment is not None:
            LOGGER.info(
                f"finished exp uuid is: {orch.active_experiment.experiment_uuid}, adding matching acts to it"
            )
            await orch.put_lbuf(
                {
                    orch.active_experiment.experiment_uuid: {
                        "experiment_name": orch.active_experiment.experiment_name,
                        "status": HloStatus.finished.value,
                    }
                }
            )

            # orch.active_experiment.dispatched_actions = []

            # TODO use exp uuid to filter actions?
            # orch.active_experiment.dispatched_actions = (
            #     orch.globalstatusmodel.finish_experiment(
            #         exp_uuid=orch.active_experiment.experiment_uuid
            #     )
            # )
            # set exp status to finished
            orch.active_experiment.replace_experiment_status(
                HloStatus.active, HloStatus.finished
            )
            orch.active_experiment.experiment_finished_timestamp = set_time(
                offset=orch.ntp_offset
            )

            # post-process experiment object
            if orch.exp_postprocessors:
                for epp, libname in zip(
                    orch.exp_postprocessors, orch.exp_postprocess_libs
                ):
                    LOGGER.info(
                        f"Running custom EXP post-processor: {os.path.basename(libname).split('.py')[0]}"
                    )
                    loop = asyncio.get_running_loop()
                    postprocessor = epp(orch.active_experiment, orch)
                    await loop.run_in_executor(None, postprocessor.process)

            # add finished exp to seq
            # !!! add to dispatched_experiments
            orch.active_sequence.dispatched_experiments.append(
                deepcopy(orch.active_experiment.get_exp())
            )

            # write new updated seq
            await orch.write_active_sequence_seq()

            # write final exp
            orch.active_experiment.finished_global_params = {
                k: v for k, v in orch.global_params.items() if k != "_fast_samples_in"
            }
            await orch.write_exp(orch.active_experiment)

            orch.last_experiment = deepcopy(orch.active_experiment)

            orch.register_obj_uuid(
                orch.active_experiment.experiment_uuid,
                {
                    "experiment_name": orch.active_experiment.experiment_name,
                    "experiment_params": orch.active_experiment.experiment_params,
                    "experiment_timestamp": f"{orch.active_experiment.experiment_timestamp: %m-%d %H:%M:%S}",
                    "experiment_finished_timestamp": f"{orch.active_experiment.experiment_finished_timestamp: %m-%d %H:%M:%S}",
                    "experiment_status": HloStatus.finished.value,
                    "sequence_label": orch.active_sequence.sequence_label,
                    "campaign_name": (
                        orch.active_sequence.campaign_name
                        if orch.active_sequence.campaign_name
                        else None
                    ),
                },
                "experiment",
            )
            orch.active_experiment = None

            # DB server call to finish_yml if DB exists
            orch.aloop.create_task(move_dir(orch.last_experiment, base=orch))

    async def write_active_experiment_exp(self):
        """Persist the active experiment to disk after snapshotting initial global params."""
        orch = self.orch
        orch.active_experiment.initial_global_params = {
            k: v for k, v in orch.global_params.items() if k != "_fast_samples_in"
        }
        await orch.write_exp(orch.active_experiment)

    async def write_active_sequence_seq(self):
        """Persist the active sequence to disk after snapshotting initial global params."""
        orch = self.orch
        orch.active_sequence.initial_global_params = {
            k: v for k, v in orch.global_params.items() if k != "_fast_samples_in"
        }
        await orch.write_seq(orch.active_sequence)

    def start_wait(self, active: Active):
        """Schedule :meth:`dispatch_wait_task` for ``active`` as a background task."""
        orch = self.orch
        orch.wait_task = asyncio.create_task(orch.dispatch_wait_task(active))

    async def dispatch_wait_task(self, active: Active, print_every_secs: int = 5):
        """Run a long wait action off the HTTP handler so the client doesn't time out.

        Args:
            active: ``Active`` carrying the ``waittime`` parameter.
            print_every_secs: Interval between progress log messages.

        Returns:
            The finished action returned by ``active.finish()``.
        """
        orch = self.orch
        # handle long waits as a separate task so HTTP timeout doesn't occur
        waittime = active.action.action_params["waittime"]
        LOGGER.info(" ... wait action:")
        orch.current_wait_ts = time.time()
        last_print_time = orch.current_wait_ts
        check_time = orch.current_wait_ts
        while check_time - orch.current_wait_ts < waittime:
            if check_time - last_print_time > print_every_secs - 0.01:
                LOGGER.info(
                    f" ... orch waited {(check_time-orch.current_wait_ts):.1f} sec / {waittime:.1f} sec"
                )
                last_print_time = check_time
            await asyncio.sleep(0.01)  # 10 msec sleep
            check_time = time.time()
        LOGGER.info(" ... wait action done")
        finished_action = await active.finish()
        orch.last_wait_ts = check_time
        return finished_action
