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
from helao.framework.app.base_api import FrameworkBase, ActionContext
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

    # an .act meta file was written
    assert list(tmp_path.rglob("*.act")), "no .act meta written"


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
