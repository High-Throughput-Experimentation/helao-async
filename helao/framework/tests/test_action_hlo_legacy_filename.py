"""TDD tests for legacy-faithful streaming HLO filenames + act.yml recording.

Bug (TEST_sub_wait_acquire / SIM acquire_data):
  1. The streaming ``.hlo`` filename did not match the legacy naming convention
     ``{action_abbr}-{orch_submit_order}.{action_order}.{action_retry}.{action_split}__{filenum}.hlo``.
     The framework named it ``{action_name}-{file_conn_key}.hlo`` instead.
  2. The ``.hlo`` was never recorded in the action's ``-act.yml`` (``files`` list
     stayed empty) because ``open_file`` never appended a ``FileInfo``.

Root cause: the framework opened the file *eagerly* in ``contain_action`` —
before the endpoint sets ``action_abbr`` and without recording a ``FileInfo``.
Legacy opens the file *lazily on first data write* (base.py:1633-1647), which
captures ``action_abbr`` and appends a ``FileInfo`` (base.py:1551).

RED tests written BEFORE the fix — must FAIL before, PASS after.
"""
import hashlib
from pathlib import Path
from uuid import UUID
from datetime import datetime

import pytest

from helao.framework.domain.run_models import RunAction
from helao.framework.domain import lifecycle
from helao.framework.app.base_api import FrameworkBase
from helao.framework.adapters.fs_storage import FsStorage
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.fakes.transport import FakeTransport
from helao.helpers.yml_tools import yml_load

FIXED_NOW = datetime(2026, 6, 27, 5, 0, 0)
CONN_KEY = UUID("00000000-0000-0000-0000-0000000000aa")
ACT_UUID = UUID("00000000-0000-0000-0000-0000000000cc")


def _base(tmp_path) -> FrameworkBase:
    return FrameworkBase(
        server_key="SIM",
        storage=FsStorage(save_root=str(tmp_path)),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
        transport=FakeTransport(),
    )


def _data_action(**overrides) -> RunAction:
    kwargs = dict(
        action_name="acquire_data",
        action_uuid=ACT_UUID,
        action_timestamp=FIXED_NOW,
        sequence_timestamp=FIXED_NOW,
        experiment_timestamp=FIXED_NOW,
        sequence_name="seq",
        experiment_name="exp",
        save_act=True,
        save_data=True,
        orch_submit_order=2,
        file_conn_keys=[CONN_KEY],
    )
    kwargs.update(overrides)
    a = RunAction(**kwargs)
    a.action_server.server_name = "SIM"
    a.sequence_output_dir = lifecycle.sequence_output_dir(a)
    a.experiment_output_dir = lifecycle.experiment_output_dir(a)
    a.action_output_dir = lifecycle.action_output_dir(a)
    return a


# legacy: {abbr}-{orch_submit_order}.{action_order}.{action_retry}.{action_split}__{filenum}.hlo
EXPECTED_NAME = "WsSim-2.0.0.0__0.hlo"


@pytest.mark.asyncio
async def test_streaming_hlo_uses_legacy_filename(tmp_path):
    base = _base(tmp_path)
    action = _data_action()

    session = await base.contain_action(action)
    # endpoint sets the abbr AFTER setup_and_contain_action (mirrors ws_simulator)
    session.action.action_abbr = "WsSim"
    await session.enqueue_data({CONN_KEY: {"epoch_s": 1.0, "x": 42}})
    await session.finish()

    hlo_files = [p.name for p in Path(tmp_path).rglob("*.hlo")]
    assert EXPECTED_NAME in hlo_files, (
        f"Expected legacy-named hlo {EXPECTED_NAME!r}; found {hlo_files} "
        f"(all files: {[str(p) for p in Path(tmp_path).rglob('*')]})"
    )


@pytest.mark.asyncio
async def test_streaming_hlo_recorded_in_act_yml(tmp_path):
    base = _base(tmp_path)
    action = _data_action()

    session = await base.contain_action(action)
    session.action.action_abbr = "WsSim"
    await session.enqueue_data({CONN_KEY: {"epoch_s": 1.0, "x": 42}})
    await session.finish()

    act_files = list(Path(tmp_path).rglob("*-act.yml"))
    assert act_files, "no -act.yml written"
    doc = yml_load(str(act_files[0]))
    recorded = [f.get("file_name") for f in (doc.get("files") or [])]
    assert EXPECTED_NAME in recorded, (
        f"hlo {EXPECTED_NAME!r} not recorded in -act.yml files list; got {recorded}"
    )


@pytest.mark.asyncio
async def test_no_data_action_writes_no_hlo(tmp_path):
    """Legacy parity: a save_data action that enqueues NO data writes no .hlo."""
    base = _base(tmp_path)
    action = _data_action()

    session = await base.contain_action(action)
    session.action.action_abbr = "WsSim"
    await session.finish()  # no enqueue_data

    hlo_files = list(Path(tmp_path).rglob("*.hlo"))
    assert not hlo_files, (
        f"no-data action must not create an .hlo (legacy lazy open); found {hlo_files}"
    )
