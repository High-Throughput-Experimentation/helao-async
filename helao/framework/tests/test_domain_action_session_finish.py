"""Tests for ActionSession.finish / _finish (Wave 4.2).

Ports ``Active.finish`` / ``_finish`` / ``relocate_files`` / ``track_file``:
drain queued data deterministically, export ``to_global_params`` through the
injected TRANSPORT port, write the ``.act`` meta, run post-processors, schedule
relocation of tracked aux files, and emit the final ``finished`` status.

All effects go through the injected fakes; no real I/O.
"""

import asyncio
from datetime import datetime
from uuid import UUID

from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.sample import SolidSample
from helao.framework.domain.run_models import RunAction
from helao.framework.domain.executor import Executor
from helao.framework.domain.action_session import ActionSession

from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.fakes.eventsink import FakeEventSink
from helao.framework.adapters.fakes.clock import FakeClock
from helao.framework.adapters.fakes.transport import FakeTransport

FIXED_NOW = datetime(2026, 6, 22, 14, 5, 6)
FINISH_NOW = datetime(2026, 6, 22, 14, 30, 0)
FIXED_UUID = UUID("00000000-0000-0000-0000-0000000000aa")
FILE_CONN = UUID("00000000-0000-0000-0000-0000000000ff")


def _run_action(**overrides):
    kwargs = dict(
        action_name="dummy_act",
        action_uuid=FIXED_UUID,
        action_timestamp=FIXED_NOW,
        sequence_timestamp=FIXED_NOW,
        experiment_timestamp=FIXED_NOW,
        sequence_uuid=FIXED_UUID,
        experiment_uuid=FIXED_UUID,
        sequence_name="seq",
        experiment_name="exp",
        action_output_dir="26.25/0622/x__0__srv__dummy_act",
        save_act=True,
        save_data=True,
        file_conn_keys=[FILE_CONN],
    )
    kwargs.update(overrides)
    return RunAction(**kwargs)


def _make_session(action=None, postprocessors=None):
    storage = FakeStorage()
    eventsink = FakeEventSink()
    clock = FakeClock()
    transport = FakeTransport()
    if action is None:
        action = _run_action()

    class _Wrap:
        def __init__(self, act):
            self.action = act

    executor = Executor(active=_Wrap(action))
    session = ActionSession(
        action,
        storage=storage,
        eventsink=eventsink,
        clock=clock,
        executor=executor,
        transport=transport,
        now_factory=lambda: FINISH_NOW,
        uuid_factory=lambda: FIXED_UUID,
        postprocessors=postprocessors,
    )
    return session, storage, eventsink, clock, transport


# --- core finish ---------------------------------------------------------------


def test_finish_stamps_finished_status_and_timestamp():
    session, storage, eventsink, clock, transport = _make_session()
    session.action.action_status = [HloStatus.active]
    asyncio.run(session.finish())
    assert HloStatus.finished in session.action.action_status
    assert HloStatus.active not in session.action.action_status
    assert session.action.action_finished_timestamp == FINISH_NOW


def test_finish_drains_pending_data_counters_balance():
    session, *_ = _make_session()
    asyncio.run(session.enqueue_data({FILE_CONN: {"v": 1}}))
    asyncio.run(session.enqueue_data({FILE_CONN: {"v": 2}}))
    assert session.num_data_queued == 2
    asyncio.run(session.finish())
    assert session.num_data_written == session.num_data_queued


def test_finish_writes_act_meta_and_emits_final_status():
    session, storage, eventsink, *_ = _make_session()
    asyncio.run(session.finish())
    # <ts>-act.yml meta written (legacy filename, run-kind-prefixed)
    assert any(k.endswith("-act.yml") for k in storage.meta_docs)
    # the written meta has a leading file_type: action key
    act_key = next(k for k in storage.meta_docs if k.endswith("-act.yml"))
    assert storage.meta_docs[act_key].get("file_type") == "action"
    # a finished status emitted
    assert any(
        HloStatus.finished.value in [str(s) for s in p.get("action_status", [])]
        for p in eventsink.statuses
    )


# --- to_global_params export via transport -------------------------------------


def test_finish_exports_global_params_list_via_transport():
    action = _run_action(
        to_global_params=["alpha"],
        action_params={"alpha": 1, "beta": 2},
        orch_key="orch",
        orch_host="h",
        orch_port=8000,
    )
    session, storage, eventsink, clock, transport = _make_session(action=action)
    asyncio.run(session.finish())
    assert len(transport.published) == 1
    msg = transport.published[0]
    assert msg.name == "update_global_params"
    assert msg.payload == {"alpha": 1}


def test_finish_exports_global_params_dict_mapping_via_transport():
    action = _run_action(
        to_global_params={"alpha": "renamed"},
        action_output={"alpha": 42},
    )
    session, storage, eventsink, clock, transport = _make_session(action=action)
    asyncio.run(session.finish())
    assert transport.published[0].payload == {"renamed": 42}


def test_finish_no_transport_publish_when_no_global_params():
    session, storage, eventsink, clock, transport = _make_session()
    asyncio.run(session.finish())
    assert transport.published == []


# --- post-processors -----------------------------------------------------------


def test_finish_runs_postprocessors():
    session, storage, *_ = _make_session(postprocessors=["my_pp"])
    asyncio.run(session.finish())
    assert len(storage.postproc_calls) == 1
    assert storage.postproc_calls[0][0] == "my_pp"


# --- aux file relocation -------------------------------------------------------


def test_track_file_then_finish_relocates_aux_files():
    session, storage, *_ = _make_session()
    # an aux file that lives outside the action output dir
    asyncio.run(
        session.track_file("aux_type", "/some/other/dir/extra.csv", [SolidSample(sample_no=1, plate_id=1)])
    )
    assert "/some/other/dir/extra.csv" in [str(p) for p in session.action.aux_file_paths]
    asyncio.run(session.finish())
    assert len(storage.relocations) == 1
    src, dst = storage.relocations[0]
    assert src == "/some/other/dir/extra.csv"
    assert "extra.csv" in dst


def test_track_file_inside_output_dir_not_relocated():
    session, storage, *_ = _make_session()
    inside = f"{session.action.action_output_dir}/local.csv"
    asyncio.run(session.track_file("aux_type", inside, []))
    assert session.action.aux_file_paths == []
    asyncio.run(session.finish())
    assert storage.relocations == []


# --- error / estop branches ----------------------------------------------------


def test_finish_appends_errored_status_on_error_code():
    action = _run_action(error_code=ErrorCodes.critical)
    session, *_ = _make_session(action=action)
    session.action.action_status = [HloStatus.active]
    asyncio.run(session.finish())
    assert HloStatus.errored in session.action.action_status
    assert HloStatus.finished in session.action.action_status


def test_finish_estop_sets_estopped_status():
    session, *_ = _make_session()
    session.action.action_status = [HloStatus.active]
    asyncio.run(session.finish(end_state=HloStatus.estopped))
    assert HloStatus.estopped in session.action.action_status
    assert HloStatus.active not in session.action.action_status


# --- file handles closed on finish ---------------------------------------------


def test_finish_closes_open_file_handles():
    session, storage, *_ = _make_session()
    handle = asyncio.run(session.open_file(FILE_CONN, header=""))
    asyncio.run(session.finish())
    assert handle.closed is True
    assert session._open_handles == {}


# --- manual action finish writes synthetic meta --------------------------------


def test_finish_manual_action_writes_exp_seq_meta():
    action = RunAction(action_name="manual_act", save_act=True, save_data=False)
    session, storage, *_ = _make_session(action=action)
    asyncio.run(session.promote_manual())
    asyncio.run(session.finish())
    # legacy filenames: <ts>-exp.yml, <ts>-seq.yml (not uuid.exp / uuid.seq)
    assert any(k.endswith("-exp.yml") for k in storage.meta_docs), \
        f"no *-exp.yml found in {list(storage.meta_docs)}"
    assert any(k.endswith("-seq.yml") for k in storage.meta_docs), \
        f"no *-seq.yml found in {list(storage.meta_docs)}"
