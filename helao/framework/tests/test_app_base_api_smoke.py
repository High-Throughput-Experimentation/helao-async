"""End-to-end wiring smoke test for the app layer (Task 5.1).

Builds a :class:`FrameworkBase` wired with the REAL adapters — ``FsStorage``
(tmp root), ``QueueEventSink``, ``NtpClock`` — and the transport FAKE, then runs
a dummy-executor action end-to-end through the preserved public surface
(``setup_and_contain_action`` -> drive the executor loop -> ``finish``). Asserts
that an ``.hlo`` file with the correct bytes lands on disk and that the active is
discoverable via ``get_active_info``.

Also exercises ``app/factory.py``'s ``makeApp`` to prove it constructs a real
FastAPI app exposing an action endpoint that runs the dummy executor end-to-end.
"""
import asyncio
from datetime import datetime
from uuid import UUID

from fastapi.testclient import TestClient

from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.domain.run_models import RunAction
from helao.framework.domain.executor import Executor
from helao.framework.adapters.fs_storage import FsStorage
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.fakes.transport import FakeTransport
from helao.framework.domain.action_session import ActionSession
from helao.framework.app.base_api import FrameworkBase, ActionContext, ACTION_CTX
from helao.framework.app.factory import makeApp

FIXED_NOW = datetime(2026, 6, 22, 14, 5, 6)
FIXED_UUID = UUID("00000000-0000-0000-0000-0000000000aa")
FILE_CONN = UUID("00000000-0000-0000-0000-0000000000ff")


def _run_action(**overrides) -> RunAction:
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


def test_setup_and_contain_then_finish_writes_hlo(tmp_path):
    storage = FsStorage(save_root=str(tmp_path))
    eventsink = QueueEventSink()
    clock = NtpClock()
    transport = FakeTransport()

    base = FrameworkBase(
        server_key="srv",
        storage=storage,
        eventsink=eventsink,
        clock=clock,
        transport=transport,
    )

    action = _run_action()

    async def _drive():
        active = await base.setup_and_contain_action(
            ActionContext(action=action), header="epoch_ns: 1"
        )
        # public surface preserved
        assert base.get_active_info(action.action_uuid) is not None

        # open the streaming HLO file connection and stream a row
        await active.open_file(FILE_CONN, header="epoch_ns: 1")
        await active.enqueue_data({FILE_CONN: {"signal": 42}})
        # drive a dummy oneoff executor end-to-end
        executor = Executor(active=active)

        async def _exec(self):
            return {"data": {"signal": 7}, "error": ErrorCodes.none}

        executor.set_exec(_exec)
        return await active.action_loop_task(executor)

    result = asyncio.run(_drive())
    assert HloStatus.finished in result.action_status

    # an HLO file appeared on disk with the expected header + separator + row
    hlo_files = list(tmp_path.rglob("*.hlo"))
    assert hlo_files, "no .hlo file was written"
    content = hlo_files[0].read_text(encoding="utf-8")
    assert content.startswith("epoch_ns: 1\n%%\n")
    assert "signal" in content

    # a <ts>-act.yml meta file was written (legacy filename)
    assert list(tmp_path.rglob("*-act.yml")), "no *-act.yml meta written"


def _make_base(tmp_path, **kwargs) -> FrameworkBase:
    return FrameworkBase(
        server_key="srv",
        storage=FsStorage(save_root=str(tmp_path)),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
        transport=FakeTransport(),
        **kwargs,
    )


def test_executors_registry_initialized_empty(tmp_path):
    base = _make_base(tmp_path)
    assert base.executors == {}


def test_server_config_exposes_params(tmp_path):
    base = _make_base(tmp_path, server_cfg={"params": {"x": 1}})
    assert base.server_params == {"x": 1}


def test_server_params_default_empty(tmp_path):
    base = _make_base(tmp_path)
    assert base.server_params == {}
    assert base.server_cfg == {}


def test_stamp_lbuf_dict_shape_and_get_lbuf(tmp_path):
    base = _make_base(tmp_path)
    stamped = base._stamp_lbuf_dict({"k": 1})
    assert set(stamped) == {"k"}
    value, ts = stamped["k"]
    assert value == 1
    assert isinstance(ts, float)
    # get_lbuf returns whatever lives in the buffer
    base.live_buffer["k"] = (1, ts)
    assert base.get_lbuf("k") == (1, ts)


def test_live_buffer_drain_via_myinit(tmp_path):
    base = _make_base(tmp_path)

    async def _drive():
        await base.myinit()
        await base.put_lbuf({"k": 1})
        # let the drain task run
        for _ in range(100):
            await asyncio.sleep(0)
            if "k" in base.live_buffer:
                break
        value, ts = base.get_lbuf("k")
        base._live_task.cancel()
        return value, ts

    value, ts = asyncio.run(_drive())
    assert value == 1
    assert isinstance(ts, float)


def test_setup_and_contain_action_no_arg_uses_action_ctx(tmp_path):
    base = _make_base(tmp_path)
    action = _run_action()
    token = ACTION_CTX.set(ActionContext(action=action))
    try:

        async def _drive():
            return await base.setup_and_contain_action(header="epoch_ns: 1")

        session = asyncio.run(_drive())
        assert isinstance(session, ActionSession)
        assert session.action.action_uuid == action.action_uuid
    finally:
        ACTION_CTX.reset(token)


def test_setup_and_contain_action_no_ctx_raises(tmp_path):
    base = _make_base(tmp_path)
    assert ACTION_CTX.get() is None

    async def _drive():
        await base.setup_and_contain_action()

    try:
        asyncio.run(_drive())
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "ACTION_CTX" in str(exc)


def test_make_app_runs_dummy_executor_end_to_end(tmp_path):
    app = makeApp("srv", save_root=str(tmp_path))
    client = TestClient(app)
    resp = client.post("/srv/run_dummy", json={"value": 99})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "finished"
    assert body["action_uuid"]
    # the endpoint produced an HLO file on disk
    assert list(tmp_path.rglob("*.hlo")), "endpoint wrote no .hlo file"
