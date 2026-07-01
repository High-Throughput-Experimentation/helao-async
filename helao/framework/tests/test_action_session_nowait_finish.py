"""finish() awaits in-flight enqueue_data_nowait() writes before closing.

PAL's archive_custom_query_sample does enqueue_data_nowait(...) then finish()
immediately. The nowait write is a fire-and-forget task that lazily opens the
.hlo; if it ran after _close_conns the handle leaked and locked the
RUNS_ACTIVE->FINISHED promotion on Windows (WinError 32). finish() must await
those tasks first, so the opened handle is tracked and closed.
"""
import asyncio
from datetime import datetime
from uuid import UUID

from helao.framework.app.base_api import FrameworkBase
from helao.framework.adapters.fs_storage import FsStorage
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.fakes.transport import FakeTransport
from helao.framework.domain.run_models import RunAction
from helao.framework.models.data import DataModel

FIXED_NOW = datetime(2026, 7, 1, 16, 14, 3)
FILE_CONN = UUID("00000000-0000-0000-0000-0000000000ff")


def _base(tmp_path):
    return FrameworkBase(
        server_key="PAL",
        storage=FsStorage(save_root=str(tmp_path)),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
        transport=FakeTransport(),
    )


def test_finish_awaits_nowait_write_no_leaked_handle(tmp_path):
    action = RunAction(
        action_name="archive_custom_query_sample",
        action_uuid=UUID("00000000-0000-0000-0000-0000000000aa"),
        action_timestamp=FIXED_NOW,
        sequence_timestamp=FIXED_NOW,
        experiment_timestamp=FIXED_NOW,
        sequence_name="seq",
        experiment_name="exp",
        action_output_dir="26.26/0701/x__0__PAL__archive_custom_query_sample",
        save_act=True,
        save_data=True,
        file_conn_keys=[FILE_CONN],
    )

    async def _drive():
        base = _base(tmp_path)
        session = await base.contain_action(action)
        dm = DataModel(data={FILE_CONN: {"sample": ["s1"], "error_code": [0]}})
        session.enqueue_data_nowait(dm, action=action)
        # scheduled fire-and-forget, not yet awaited
        assert session._enqueue_tasks
        await session.finish()
        return session

    session = asyncio.run(_drive())

    # finish awaited + cleared the nowait task, and closed the handle it opened
    assert session._enqueue_tasks == []
    assert session._open_handles == {}
    # the deferred write actually landed on disk
    hlo = list(tmp_path.rglob("*.hlo"))
    assert hlo, "nowait data was never written before finish"
    assert "sample" in hlo[0].read_text(encoding="utf-8")
