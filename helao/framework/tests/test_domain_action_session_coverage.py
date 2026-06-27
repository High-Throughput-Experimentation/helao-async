"""Targeted branch-coverage tests for ActionSession (Task 5.2 close-out).

These exercise the remaining uncovered branches of
``helao.framework.domain.action_session`` that the happy-path / split / finish
suites do not reach: executor-loop error and exception paths, manual-stop,
``save_data``-disabled short-circuits, nonblocking status skips, the
``DataModel``-typed enqueue branch, and the ``finish`` early-return when not all
siblings are terminal. All effects go through the injected fakes; no real I/O.
"""
import asyncio
from datetime import datetime
from uuid import UUID

from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.data import DataModel
from helao.framework.models.sample import SolidSample
from helao.framework.domain.run_models import RunAction
from helao.framework.domain.executor import Executor
from helao.framework.domain.action_session import ActionSession

from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.fakes.eventsink import FakeEventSink
from helao.framework.adapters.fakes.clock import FakeClock
from helao.framework.adapters.fakes.transport import FakeTransport

FIXED_NOW = datetime(2026, 6, 22, 14, 5, 6)
FIXED_UUID = UUID("00000000-0000-0000-0000-0000000000aa")
OTHER_UUID = UUID("00000000-0000-0000-0000-0000000000bb")
FILE_CONN = UUID("00000000-0000-0000-0000-0000000000ff")


def _run_action(**overrides):
    kwargs = dict(
        action_name="dummy_act",
        action_uuid=FIXED_UUID,
        action_timestamp=FIXED_NOW,
        sequence_timestamp=FIXED_NOW,
        experiment_timestamp=FIXED_NOW,
        sequence_name="seq",
        experiment_name="exp",
        action_output_dir="26.25/0622/x__0__srv__dummy_act",
        save_act=True,
        save_data=True,
        file_conn_keys=[FILE_CONN],
    )
    kwargs.update(overrides)
    return RunAction(**kwargs)


def _make_session(action=None):
    if action is None:
        action = _run_action()

    class _Wrap:
        def __init__(self, act):
            self.action = act

    executor = Executor(active=_Wrap(action))
    session = ActionSession(
        action,
        storage=FakeStorage(),
        eventsink=FakeEventSink(),
        clock=FakeClock(),
        executor=executor,
        transport=FakeTransport(),
        now_factory=lambda: FIXED_NOW,
        uuid_factory=lambda: FIXED_UUID,
    )
    return session, executor


# --- write_file save_data disabled ---------------------------------------------


def test_write_file_returns_none_when_save_data_disabled():
    action = _run_action(save_data=False, save_act=False)
    session, _ = _make_session(action)
    rel = asyncio.run(session.write_file("body", "aux_type", filename="x.csv"))
    assert rel is None


def test_write_file_autogenerates_filename():
    session, _ = _make_session()
    rel = asyncio.run(session.write_file("body", "aux_type"))
    assert rel is not None and rel.endswith(".aux_type")


# --- enqueue_data with a ready DataModel ---------------------------------------


def test_enqueue_accepts_datamodel_instance():
    session, _ = _make_session()
    dm = DataModel(data={FILE_CONN: {"v": 1}}, errors=[], status=HloStatus.active)
    asyncio.run(session.enqueue_data(dm))
    assert session.num_data_queued == 1


# --- add_status nonblocking skip on explicit action ---------------------------


def test_add_status_skips_for_nonblocking_explicit_action():
    session, _ = _make_session()
    other = _run_action(action_uuid=OTHER_UUID, nonblocking=True)
    asyncio.run(session.add_status(action=other))
    assert session.eventsink.statuses == []


# --- append_sample 'out' branch + defaults filled -----------------------------


def test_append_sample_out_fills_defaults():
    session, _ = _make_session()
    smp = SolidSample(sample_no=1, plate_id=1)
    asyncio.run(session.append_sample([smp], "out"))
    assert len(session.action.samples_out) == 1
    placed = session.action.samples_out[0]
    assert placed.action_uuid == [FIXED_UUID]
    assert placed.inheritance is not None
    assert placed.status


# --- executor loop: pre_exec error short-circuits to finish --------------------


def test_loop_pre_exec_error_finishes_immediately():
    session, executor = _make_session()

    async def _pre(self):
        return {"error": ErrorCodes.critical}

    executor.set_pre_exec(_pre)
    result = asyncio.run(session.action_loop_task(executor))
    assert result.error_code == ErrorCodes.critical
    assert HloStatus.finished in result.action_status


# --- executor loop: _exec raises -> caught, finishes ---------------------------


def test_loop_exec_exception_is_caught():
    session, executor = _make_session()

    async def _exec(self):
        raise RuntimeError("boom")

    executor.set_exec(_exec)
    result = asyncio.run(session.action_loop_task(executor))
    assert HloStatus.finished in result.action_status


# --- executor loop: poll raises then terminal ----------------------------------


def test_loop_poll_exception_then_continues():
    session, executor = _make_session()
    executor.oneoff = False
    executor.poll_rate = 0
    state = {"n": 0}

    async def _poll(self):
        state["n"] += 1
        raise RuntimeError("poll boom")

    executor.set_poll(_poll)
    result = asyncio.run(session.action_loop_task(executor))
    # an exception yields result={}, whose default status is terminal, so the
    # loop runs the poll exactly once then exits.
    assert state["n"] == 1
    assert HloStatus.finished in result.action_status


# --- executor loop: poll error_code propagates + poll_rate sleep ---------------


def test_loop_poll_error_code_propagates_and_sleeps():
    session, executor = _make_session()
    executor.oneoff = False
    executor.poll_rate = 0.01  # nonzero to hit the _sleep branch
    state = {"n": 0}

    async def _poll(self):
        state["n"] += 1
        if state["n"] < 2:
            return {"data": {}, "error": ErrorCodes.none, "status": HloStatus.active}
        return {"data": {}, "error": ErrorCodes.critical, "status": HloStatus.finished}

    executor.set_poll(_poll)
    result = asyncio.run(session.action_loop_task(executor))
    assert result.error_code == ErrorCodes.critical


# --- executor loop: manual_stop hook + post_exec error -------------------------


def test_loop_manual_stop_and_post_exec_error():
    session, executor = _make_session()
    session.manual_stop = True
    stopped = {"hit": False}

    async def _manual_stop(self):
        stopped["hit"] = True
        return {"error": ErrorCodes.critical}

    async def _post(self):
        return {"data": {}, "error": ErrorCodes.critical}

    executor.set_manual_stop(_manual_stop)
    executor.set_post_exec(_post)
    asyncio.run(session.action_loop_task(executor))
    assert stopped["hit"] is True


# --- finish: not-all-terminal early return -------------------------------------


def test_finish_partial_uuid_list_returns_without_finalizing():
    session, _ = _make_session()
    # add a distinct prior sibling so action_list has length 2
    prior = _run_action(action_uuid=OTHER_UUID)
    prior.action_status = [HloStatus.active]
    session.action_list = [session.action, prior]
    # finish only the current action, not the prior one -> not all terminal
    result = asyncio.run(session.finish(finish_uuid_list=[session.action.action_uuid]))
    # the prior sibling is still not finished -> early-return path is taken
    assert HloStatus.finished not in prior.action_status
    assert result is session.action


# --- _sleep yields without wall-clock dependency -------------------------------


def test_sleep_is_cooperative_yield():
    session, _ = _make_session()
    asyncio.run(session._sleep(123.0))  # returns promptly regardless of arg


# --- __init__ defensive save-flag defaults (None-tolerant construction) --------


def test_init_defensive_save_flag_defaults():
    # RunAction validates save_* as bools, so build a None-carrying action via
    # model_construct to exercise the legacy-compat None defaulting in __init__.
    action = RunAction.model_construct(
        action_name="dummy_act",
        action_uuid=FIXED_UUID,
        action_output_dir="d",
        save_data=None,
        save_act=None,
        file_conn_keys=[FILE_CONN],
    )

    class _Wrap:
        def __init__(self, act):
            self.action = act

    session = ActionSession(
        action,
        storage=FakeStorage(),
        eventsink=FakeEventSink(),
        clock=FakeClock(),
        executor=Executor(active=_Wrap(action)),
    )
    assert session.action.save_data is False
    assert session.action.save_act is False


# --- myinit manual action writes synthetic exp/seq meta ------------------------


def test_myinit_manual_action_writes_synthetic_meta():
    action = _run_action(manual_action=True)
    session, _ = _make_session(action)
    asyncio.run(session.myinit())
    keys = list(session.storage.meta_docs.keys())
    # legacy filenames: <ts>-seq.yml, <ts>-exp.yml
    assert any(k.endswith("-seq.yml") for k in keys), \
        f"no *-seq.yml found in {keys}"
    assert any(k.endswith("-exp.yml") for k in keys), \
        f"no *-exp.yml found in {keys}"


# --- append_sample edge branches -----------------------------------------------


def test_append_sample_empty_list_returns_early():
    session, _ = _make_session()
    asyncio.run(session.append_sample([], "in"))
    assert session.eventsink.statuses == []


def test_append_sample_preserves_preset_inheritance_and_status():
    from helao.framework.models.sample import SampleInheritance, SampleStatus

    session, _ = _make_session()
    smp = SolidSample(sample_no=1, plate_id=1)
    smp.inheritance = SampleInheritance.give_only
    smp.status = [SampleStatus.destroyed]
    asyncio.run(session.append_sample([smp], "in"))
    placed = session.action.samples_in[0]
    assert placed.inheritance == SampleInheritance.give_only
    assert placed.status == [SampleStatus.destroyed]


def test_append_sample_tags_assembly_parts():
    from helao.framework.models.sample import AssemblySample

    session, _ = _make_session()
    part = SolidSample(sample_no=2, plate_id=1)
    assembly = AssemblySample(parts=[part])
    asyncio.run(session.append_sample([assembly], "out"))
    tagged = session.action.samples_out[0]
    assert tagged.parts[0].action_uuid == [FIXED_UUID]


# --- finish: skip an already-finished sibling ----------------------------------


def test_finish_skips_already_finished_action():
    session, _ = _make_session()
    session.action.action_status = [HloStatus.finished]
    result = asyncio.run(session.finish())
    # remains finished, no errored appended, no exception
    assert session.action.action_status.count(HloStatus.finished) == 1
    assert result is session.action


# --- finish: global-export resolves from action_output -------------------------


def test_finish_global_export_reads_action_output():
    action = _run_action(to_global_params=["beta"])
    action.action_output = {"beta": 7}
    session, _ = _make_session(action)
    asyncio.run(session.finish())
    msgs = session.transport.published
    assert msgs and msgs[0].payload == {"beta": 7}


def test_finish_global_export_dict_reads_action_output():
    action = _run_action(to_global_params={"beta": "B"})
    action.action_output = {"beta": 7}
    session, _ = _make_session(action)
    asyncio.run(session.finish())
    assert session.transport.published[0].payload == {"B": 7}


def test_finish_global_export_dict_reads_action_params():
    action = _run_action(to_global_params={"beta": "B"})
    action.action_params = {"beta": 9}
    session, _ = _make_session(action)
    asyncio.run(session.finish())
    assert session.transport.published[0].payload == {"B": 9}


# --- finish: postprocessor returns an updated file list ------------------------


def test_finish_postprocessor_updates_files():
    from helao.framework.models.file import FileInfo

    action = _run_action()
    session, _ = _make_session(action)

    updated = [FileInfo(file_type="t", file_name="new.hlo")]

    async def _runpp(name, relpath, context):
        return updated

    session.storage.run_postprocessor = _runpp
    session.postprocessors = ["pp"]
    asyncio.run(session.finish())
    assert [f.file_name for f in session.action.files] == ["new.hlo"]


def test_finish_postprocessor_empty_result_keeps_files():
    action = _run_action()
    session, _ = _make_session(action)

    async def _runpp(name, relpath, context):
        return []  # empty -> the 'if updated' branch is False, files unchanged

    session.storage.run_postprocessor = _runpp
    session.postprocessors = ["pp"]
    asyncio.run(session.finish())
    assert session.action.files == []


# --- finish: manual action skips aux-file relocation ---------------------------


def test_finish_manual_action_skips_relocation():
    action = _run_action(manual_action=True)
    session, _ = _make_session(action)
    asyncio.run(
        session.track_file("aux_type", "/elsewhere/extra.csv", [])
    )
    asyncio.run(session.finish())
    # manual actions do not relocate aux files
    assert session.storage.relocations == []
