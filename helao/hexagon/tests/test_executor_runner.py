"""The native executor loop driver (B1 Task 6).

``Executor`` itself is unchanged and unmoved -- these drive a real
``helao.helpers.executor.Executor`` subclass through the runner, so the hooks
under test are the same ones the 44 deployment subclasses implement.
"""

import asyncio

import pytest

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.helpers.executor import Executor
from helao.hexagon.app.executor_runner import ExecutorRunner


class _Recorder(Executor):
    """Records which hooks fired, and stops polling after `polls` iterations."""

    def __init__(self, *args, polls: int = 2, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls: list[str] = []
        self._left = polls

    async def _pre_exec(self):
        self.calls.append("pre")
        return {"error": ErrorCodes.none}

    async def _exec(self):
        self.calls.append("exec")
        return {"error": ErrorCodes.none, "data": {}}

    async def _poll(self):
        self.calls.append("poll")
        self._left -= 1
        status = HloStatus.active if self._left > 0 else HloStatus.finished
        return {"error": ErrorCodes.none, "status": status, "data": {}}

    async def _post_exec(self):
        self.calls.append("post")
        return {"error": ErrorCodes.none}

    async def _manual_stop(self):
        self.calls.append("manual_stop")
        return {"error": ErrorCodes.none}


class _Action:
    def __init__(self):
        self.action_uuid = "uuid-1"
        self.action_name = "acquire_data"
        self.action_params = {}
        self.nonblocking = False
        self.error_code = ErrorCodes.none
        self.file_conn_keys = ["fck"]

    def as_dict(self):
        return {"action_uuid": self.action_uuid}


class _Host:
    def __init__(self):
        self.local_action_task_queue: list = []
        self.executors: dict = {}
        self.aloop = None


class _Session:
    """The session surface the runner uses, and nothing else."""

    def __init__(self):
        self.base = _Host()
        self.action = _Action()
        self.action_task = None
        self.action_loop_running = False
        self.manual_stop = False
        self.finished = False
        self.enqueued: list = []
        self.runner = ExecutorRunner(self)

    def enqueue_data_nowait(self, datamodel):
        self.enqueued.append(datamodel)

    async def finish(self):
        self.finished = True
        return self.action

    async def send_nonblocking_status(self, retry_limit: int = 3):
        return None

    async def action_loop_task(self, executor):
        return await self.runner.action_loop_task(executor)

    def executor_done_callback(self, futr):
        return self.runner.executor_done_callback(futr)


def _exec_for(session, **kw):
    return _Recorder(active=session, oneoff=False, poll_rate=0.001, **kw)


@pytest.mark.asyncio
async def test_the_full_hook_sequence_runs_once_each_around_the_poll_loop():
    s = _Session()
    ex = _exec_for(s, polls=3)
    await s.runner.action_loop_task(ex)
    assert ex.calls == ["pre", "exec", "poll", "poll", "poll", "post"]
    assert s.finished, "the action was never finished"


@pytest.mark.asyncio
async def test_a_setup_error_finishes_without_running_the_work():
    """A failed _pre_exec must not reach _exec, and must still finish."""
    s = _Session()
    ex = _exec_for(s)

    async def failing_pre():
        ex.calls.append("pre")
        return {"error": ErrorCodes.critical}

    ex._pre_exec = failing_pre
    await s.runner.action_loop_task(ex)
    assert ex.calls == ["pre"]
    assert s.finished
    assert s.action.error_code == ErrorCodes.critical


@pytest.mark.asyncio
async def test_the_session_is_registered_under_exec_id_not_the_executor():
    """stop_executor_by_id calls stop_action_task on whatever is stored here."""
    s = _Session()
    seen = {}
    ex = _exec_for(s, polls=1)
    orig = ex._poll

    async def capture():
        seen["registered"] = s.base.executors.get(ex.exec_id)
        return await orig()

    ex._poll = capture
    await s.runner.action_loop_task(ex)
    assert seen["registered"] is s, "the executor was registered instead of the session"
    assert ex.exec_id not in s.base.executors, "exec_id was not popped on completion"


@pytest.mark.asyncio
async def test_stop_action_task_ends_the_poll_loop():
    s = _Session()
    ex = _exec_for(s, polls=10_000)
    orig = ex._poll

    async def stop_after_two():
        r = await orig()
        if ex.calls.count("poll") >= 2:
            s.runner.stop_action_task()
        return r

    ex._poll = stop_after_two
    await s.runner.action_loop_task(ex)
    assert ex.calls.count("poll") == 2
    assert "manual_stop" in ex.calls, "manual stop hook did not fire"


@pytest.mark.asyncio
async def test_a_raising_poll_does_not_abort_the_action():
    """One bad poll must not kill an action mid-flight."""
    s = _Session()
    ex = _exec_for(s)

    async def boom():
        ex.calls.append("poll")
        raise RuntimeError("driver hiccup")

    ex._poll = boom
    await s.runner.action_loop_task(ex)
    assert s.finished, "a raising _poll aborted the action instead of finishing it"


@pytest.mark.asyncio
async def test_a_non_concurrent_executor_waits_for_the_head_of_the_queue():
    s = _Session()
    s.base.local_action_task_queue = ["someone-else", s.action.action_uuid]
    ex = _exec_for(s, polls=1)
    ex.concurrent = False
    task = asyncio.create_task(s.runner.action_loop_task(ex))
    await asyncio.sleep(0.05)
    assert ex.calls == [], "ran while another action held the queue head"
    s.base.local_action_task_queue.pop(0)
    await asyncio.wait_for(task, timeout=2)
    assert ex.calls[0] == "pre"
