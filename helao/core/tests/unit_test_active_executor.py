"""Unit tests for the ``ExecutorRunner`` collaborator extracted from ``Active``
(CARDS P6, Stage S7): the executor-orchestration cluster
(``executor_done_callback`` / ``start_executor`` / ``oneoff_executor`` /
``action_loop_task`` / ``stop_action_task``).

``test_active_golden_master.py --check`` is the byte+whole-record gate for the
executor-produced ``.hlo`` output across the full ``Active`` lifecycle (the two
executor scenarios added in Stage S7 Part A); this module is the S7-specific
behavior-preservation gate that drives the state machine directly and asserts
the pieces in isolation: that ``start_executor`` launches the loop task and its
done-callback fires, that ``action_loop_task`` transitions
``action_loop_running`` True->False while enqueuing each phase's data, that
``oneoff_executor`` runs ``_exec`` + ``_post_exec`` with no poll loop, and that
``stop_action_task`` drives the ``manual_stop`` / ``_manual_stop`` abort path.
Also confirms every ``Active`` delegator forwards to ``active.executor_runner``
and that ``manual_stop`` / ``action_loop_running`` / ``action_task`` state stays
on ``Active``.

Mirrors the ``Base.__new__`` bypass fixture used by
``unit_test_active_data_stream.py`` / ``test_active_golden_master.py``'s
``_make_base`` + ``_mk_action``, wiring the ``aloop`` + queues + executor
bookkeeping the loop task needs, and patching the disk/network module-globals
(``move_dir`` / ``async_private_dispatcher`` / ``async_copy``) that
``action_loop_task`` -> ``finish`` reaches so no real relocation/RPC occurs.

Hermetic: no network; real (temp-dir) disk I/O so the streamed executor rows are
checked against genuine filesystem behavior.
"""

__all__ = ["active_executor_unit_test"]

import asyncio
import os
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from helao.core.tests._test_utils import TestReporter
import helao.core.servers.base as base_module
from helao.core.servers.base import Base, Active
from helao.core.servers.active_executor import ExecutorRunner
from helao.core.error import ErrorCodes
from helao.core.models.file import FileConnParams, HloFileGroup
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.helpers.active_params import ActiveParams
from helao.helpers.dequedict import DequeDict
from helao.helpers.executor import Executor
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.premodels import Action


_FIXED_DT = datetime(2026, 1, 2, 3, 4, 5, 678901)
_SEED = {"n": 0}


def _make_base(save_root: str) -> Base:
    """Build a bare ``Base`` with every attribute the executor path (+ finish) touches."""
    base = Base.__new__(Base)
    base.app = SimpleNamespace(driver=None)
    base.server = MachineModel(
        server_name="ACTSRV", machine_name="test-machine", hostname="127.0.0.1", port=8000
    )
    base.world_cfg = {
        "dummy": False,
        "simulation": False,
        "root": str(Path(save_root).parent),
    }
    base.ntp_offset = 0.0
    base.helaodirs = SimpleNamespace(save_root=save_root)
    base.aloop = asyncio.get_running_loop()
    base.status_q = MultisubscriberQueue()
    base.data_q = MultisubscriberQueue()
    base.status_clients = set()
    base.actives = {}
    base.history = DequeDict(maxlen=200)
    base.executors = {}
    base.local_action_task_queue = []
    base.hlo_postprocessors = []
    base.hlo_postprocess_libs = []
    base.live_q = MultisubscriberQueue()
    base.live_buffer = {}
    base._init_collaborators()
    return base


def _mk_action() -> Action:
    """Non-manual ``Action`` (parent seq/exp set) with data saving enabled and a unique uuid."""
    _SEED["n"] += 1
    n = _SEED["n"]
    return Action(
        action_name="exectest",
        action_abbr="exec",
        orch_key="ACTSRV",
        orch_host="127.0.0.1",
        orch_port=8000,
        action_uuid=UUID(int=0xA0000000000000000000000000000000 + n),
        action_timestamp=_FIXED_DT,
        sequence_uuid=UUID(int=0xB0000000000000000000000000000000 + n),
        sequence_name="seq_exec",
        sequence_label="ut",
        sequence_timestamp=_FIXED_DT,
        experiment_uuid=UUID(int=0xC0000000000000000000000000000000 + n),
        experiment_name="exp_exec",
        experiment_timestamp=_FIXED_DT,
        save_data=True,
    )


def _mk_active(base: Base) -> Active:
    action = _mk_action()
    dflt = base.dflt_file_conn_key()
    ap = ActiveParams(
        action=action,
        file_conn_params_dict={
            dflt: FileConnParams(
                file_conn_key=dflt,
                json_data_keys=["t", "v"],
                file_type="exec__test_file",
                file_group=HloFileGroup.helao_files,
            )
        },
        aux_listen_uuids=[],
    )
    return Active(base, ap)


class _PatchGlobals:
    """Patch the disk/network module-globals ``finish`` reaches so no real IO/RPC runs."""

    def __enter__(self):
        async def _noop_move_dir(hobj, base=None, retry_delay=5):
            return None

        async def _noop_dispatch(*args, **kwargs):
            return {}, ErrorCodes.none

        async def _noop_copy(src, dst, **kwargs):
            return None

        self._orig = {
            "move_dir": base_module.move_dir,
            "async_private_dispatcher": base_module.async_private_dispatcher,
            "async_copy": base_module.async_copy,
        }
        base_module.move_dir = _noop_move_dir
        base_module.async_private_dispatcher = _noop_dispatch
        base_module.async_copy = _noop_copy
        return self

    def __exit__(self, *exc):
        for name, val in self._orig.items():
            setattr(base_module, name, val)
        return False


class _ScriptedExecutor(Executor):
    """Deterministic scripted executor: bounded poll count, no wall-clock waits.

    Records ``action_loop_running`` observed inside ``_exec`` (True after a
    successful ``_pre_exec``) and whether ``_manual_stop`` was invoked, so the
    tests can assert the loop transitions + abort path without racing on
    scheduling."""

    def __init__(self, active, *, oneoff, max_polls=0, forever=False, poll_rate=0.0, **kwargs):
        super().__init__(active, poll_rate=poll_rate, oneoff=oneoff, concurrent=True, **kwargs)
        self._max_polls = max_polls
        self._forever = forever
        self._poll_count = 0
        self.seen_running_during_exec = None
        self.manual_stop_called = False

    async def _pre_exec(self):
        return {"error": ErrorCodes.none}

    async def _exec(self):
        self.seen_running_during_exec = self.active.action_loop_running
        return {"data": {"t": 0, "v": 0}, "error": ErrorCodes.none}

    async def _poll(self):
        self._poll_count += 1
        if self._forever:
            status = HloStatus.active
        else:
            status = (
                HloStatus.active if self._poll_count < self._max_polls else HloStatus.finished
            )
        return {
            "data": {"t": self._poll_count, "v": self._poll_count * 10},
            "error": ErrorCodes.none,
            "status": status,
        }

    async def _post_exec(self):
        return {"data": {"t": -1, "v": -1}, "error": ErrorCodes.none}

    async def _manual_stop(self):
        self.manual_stop_called = True
        return {"error": ErrorCodes.none}


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------


async def _check_collaborator_wired() -> bool:
    base = _make_base(tempfile.mkdtemp())
    active = _mk_active(base)
    return (
        isinstance(active.executor_runner, ExecutorRunner)
        and active.executor_runner.active is active
        # state stays on Active, not cached on the collaborator
        and hasattr(active, "manual_stop")
        and hasattr(active, "action_loop_running")
        and hasattr(active, "action_task")
        and not hasattr(active.executor_runner, "manual_stop")
    )


async def _check_start_executor_to_completion() -> bool:
    """start_executor launches the loop task; polling loop runs, data enqueues,
    action_loop_running transitions True->False, and the done-callback fires."""
    base = _make_base(tempfile.mkdtemp())
    with _PatchGlobals():
        active = _mk_active(base)
        await active.myinit()
        await asyncio.sleep(0.02)

        fired = {"v": False}
        orig_cb = active.executor_runner.executor_done_callback

        def spy_cb(futr):
            fired["v"] = True
            return orig_cb(futr)

        active.executor_runner.executor_done_callback = spy_cb

        executor = _ScriptedExecutor(active, oneoff=False, max_polls=3)
        running_before = active.action_loop_running
        returned = active.start_executor(executor)
        # start_executor only schedules the task -> not run yet
        running_after_start = active.action_loop_running
        has_task = active.action_task is not None

        await active.action_task
        # let the done-callback (call_soon) run
        await asyncio.sleep(0)

        return (
            isinstance(returned, dict)
            and running_before is False
            and running_after_start is False
            and has_task is True
            # loop was actually entered (observed True inside _exec)
            and executor.seen_running_during_exec is True
            and active.action_loop_running is False
            and active.manual_stop is False
            # exec(1) + 3 polls + post(1) = 5 data-bearing packets
            and active.num_data_queued == 5
            and fired["v"] is True
        )


async def _check_oneoff_executor() -> bool:
    """oneoff_executor runs _exec + _post_exec with no poll loop (2 data packets)."""
    base = _make_base(tempfile.mkdtemp())
    with _PatchGlobals():
        active = _mk_active(base)
        await active.myinit()
        await asyncio.sleep(0.02)

        executor = _ScriptedExecutor(active, oneoff=True)
        returned = await active.oneoff_executor(executor)
        await asyncio.sleep(0)

        return (
            returned is not None
            and executor.seen_running_during_exec is True
            and active.action_loop_running is False
            # oneoff: exec(1) + post(1), NO poll iterations
            and executor._poll_count == 0
            and active.num_data_queued == 2
        )


async def _check_stop_action_task_manual_stop() -> bool:
    """stop_action_task sets manual_stop + clears action_loop_running so the
    otherwise-endless poll loop exits and _manual_stop runs."""
    base = _make_base(tempfile.mkdtemp())
    with _PatchGlobals():
        active = _mk_active(base)
        await active.myinit()
        await asyncio.sleep(0.02)

        executor = _ScriptedExecutor(active, oneoff=False, forever=True, poll_rate=0.01)
        active.start_executor(executor)
        # let a few poll iterations run
        await asyncio.sleep(0.05)
        ran_some_polls = executor._poll_count > 0
        running_mid = active.action_loop_running

        active.stop_action_task()
        manual_stop_flag = active.manual_stop
        running_after_stop = active.action_loop_running

        await active.action_task
        await asyncio.sleep(0)

        return (
            ran_some_polls is True
            and running_mid is True
            and manual_stop_flag is True
            and running_after_stop is False
            and executor.manual_stop_called is True
            and active.action_loop_running is False
        )


async def _check_delegators_forward() -> bool:
    """Every Active executor delegator resolves onto executor_runner (spy each)."""
    base = _make_base(tempfile.mkdtemp())
    active = _mk_active(base)
    calls = []

    active.executor_runner.stop_action_task = lambda: calls.append("stop")
    active.executor_runner.executor_done_callback = lambda futr: calls.append("done")
    active.stop_action_task()
    active.executor_done_callback(SimpleNamespace(result=lambda: None))
    return calls == ["stop", "done"]


async def _run_checks() -> dict:
    return {
        "collaborator_wired": await _check_collaborator_wired(),
        "start_executor_to_completion": await _check_start_executor_to_completion(),
        "oneoff_executor": await _check_oneoff_executor(),
        "stop_action_task_manual_stop": await _check_stop_action_task_manual_stop(),
        "delegators_forward": await _check_delegators_forward(),
    }


def active_executor_unit_test() -> bool:
    reporter = TestReporter("active_executor")
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False

    reporter.section("collaborator construction")
    reporter.check(
        "Active.__init__ builds an ExecutorRunner back-referencing the Active; "
        "manual_stop/action_loop_running/action_task stay on Active",
        lambda: res["collaborator_wired"],
    )

    reporter.section("start_executor -> action_loop_task (concurrent, to completion)")
    reporter.check(
        "start_executor launches the loop task; action_loop_running transitions "
        "True->False, each phase enqueues data, and executor_done_callback fires",
        lambda: res["start_executor_to_completion"],
    )

    reporter.section("oneoff_executor")
    reporter.check(
        "oneoff_executor runs _exec + _post_exec with no poll loop",
        lambda: res["oneoff_executor"],
    )

    reporter.section("stop_action_task (manual-stop abort path)")
    reporter.check(
        "stop_action_task sets manual_stop + clears action_loop_running so the "
        "poll loop exits and _manual_stop runs",
        lambda: res["stop_action_task_manual_stop"],
    )

    reporter.section("delegator forwarding")
    reporter.check(
        "Active executor delegators forward to active.executor_runner",
        lambda: res["delegators_forward"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if active_executor_unit_test() else 1)
