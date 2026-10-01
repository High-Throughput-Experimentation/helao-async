"""The native executor loop driver (B1 Task 6).

``Executor`` itself is unchanged and unmoved -- these drive a real
``helao.helpers.executor.Executor`` subclass through the runner, so the hooks
under test are the same ones the 44 deployment subclasses implement.
"""

import asyncio
from uuid import UUID

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
        self.action_task: asyncio.Task | None = None
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


# -- moved from helao/core/tests/unit_test_active_executor.py (B7b) ----------


class _DataRecorder(_Recorder):
    """A _Recorder whose exec, poll and post phases each return one data row,
    and which records whether the loop flag was up while ``_exec`` ran."""

    seen_running = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # a data row is keyed by file_conn_key, which DataModel types as a UUID
        self.active.action.file_conn_keys = [UUID(int=1)]

    async def _exec(self):
        await super()._exec()
        self.seen_running = self.active.action_loop_running
        return {"error": ErrorCodes.none, "data": {"t": 0}}

    async def _poll(self):
        result = await super()._poll()
        result["data"] = {"t": len(self.calls)}
        return result

    async def _post_exec(self):
        await super()._post_exec()
        return {"error": ErrorCodes.none, "data": {"t": -1}}


class _LoopHost(_Host):
    def __init__(self):
        super().__init__()
        self.aloop = asyncio.get_running_loop()


class _CallbackSession(_Session):
    """A _Session on a host with a running loop, recording done-callbacks."""

    def __init__(self):
        super().__init__()
        self.base = _LoopHost()
        self.fired: list = []

    def executor_done_callback(self, futr):
        self.fired.append(futr)


@pytest.mark.asyncio
async def test_start_executor_schedules_the_loop_and_its_done_callback_fires():
    """start_executor only schedules the loop; the task then holds the loop flag
    while it works, enqueues one row per phase, and fires the done-callback."""
    s = _CallbackSession()
    ex = _DataRecorder(active=s, oneoff=False, poll_rate=0.001, polls=3)

    returned = s.runner.start_executor(ex)
    assert returned == {"action_uuid": "uuid-1"}
    assert ex.calls == [], "start_executor ran the loop inline"

    task = s.action_task
    assert task is not None
    await task
    await asyncio.sleep(0)
    assert ex.seen_running is True
    assert s.action_loop_running is False
    assert s.manual_stop is False
    assert len(s.enqueued) == 5  # exec + 3 polls + post
    assert s.fired == [task]


@pytest.mark.asyncio
async def test_a_oneoff_executor_runs_exec_and_post_with_no_poll_loop():
    s = _Session()
    ex = _DataRecorder(active=s, oneoff=True, poll_rate=0.001)
    returned = await s.runner.oneoff_executor(ex)
    assert returned is s.action
    assert ex.calls == ["pre", "exec", "post"]
    assert ex.seen_running is True
    assert s.action_loop_running is False
    assert len(s.enqueued) == 2  # exec + post
