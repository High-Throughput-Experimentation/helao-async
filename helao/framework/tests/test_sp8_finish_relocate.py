"""SP8 WS-F: whole-run-directory relocation at action finish.

When an action finishes, its output directory must be promoted out of the
active run root (``RUNS_ACTIVE``) into the finished root (``RUNS_FINISHED``) so
``HelaoSyncer`` ships it. Ports the legacy ``move_dir(action, base=...)``
scheduled in ``Active._finish`` (helao/core/servers/base.py ~L2218).

Two layers under test:
  * the ``FsStorage.relocate_run`` port method directly (real tmp_path IO);
  * an action driven end-to-end through ``ActionSession.finish`` with a real
    ``FsStorage`` rooted at an active dir, asserting the dir moved.
"""

import asyncio
from datetime import datetime
from uuid import UUID

import pytest

from helao.framework.models.hlostatus import HloStatus
from helao.framework.domain.run_models import RunAction
from helao.framework.domain.executor import Executor
from helao.framework.domain.action_session import ActionSession

from helao.framework.adapters.fs_storage import FsStorage
from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.fakes.eventsink import FakeEventSink
from helao.framework.adapters.fakes.clock import FakeClock
from helao.framework.adapters.fakes.transport import FakeTransport

FIXED_NOW = datetime(2026, 6, 23, 9, 0, 0)
FINISH_NOW = datetime(2026, 6, 23, 9, 30, 0)
FIXED_UUID = UUID("00000000-0000-0000-0000-0000000000aa")
ACT_DIR = "26.25/0623/x__0__srv__dummy_act"


# --- FsStorage.relocate_run port method (direct) -------------------------------


def _seed_active_run(active_root, action_output_dir):
    """Create a populated action dir under the active root; return its path."""
    run_dir = active_root / action_output_dir
    run_dir.mkdir(parents=True)
    (run_dir / f"{FIXED_UUID}.act").write_text("file_type: action\n")
    (run_dir / "dummy_act-data.hlo").write_text("%%\n{\"v\": 1}\n")
    sub = run_dir / "aux"
    sub.mkdir()
    (sub / "extra.csv").write_text("col\n1\n")
    return run_dir


@pytest.mark.asyncio
async def test_relocate_run_moves_dir_active_to_finished(tmp_path):
    active = tmp_path / "RUNS_ACTIVE"
    storage = FsStorage(str(active))
    run_dir = _seed_active_run(active, ACT_DIR)

    await storage.relocate_run(ACT_DIR, sync_data=True)

    # active dir removed
    assert not run_dir.exists()
    # files (incl. nested) landed under RUNS_FINISHED, mirrored layout
    finished = tmp_path / "RUNS_FINISHED" / ACT_DIR
    assert (finished / f"{FIXED_UUID}.act").read_text() == "file_type: action\n"
    assert (finished / "dummy_act-data.hlo").exists()
    assert (finished / "aux" / "extra.csv").read_text() == "col\n1\n"


@pytest.mark.asyncio
async def test_relocate_run_diverts_hlo_to_nosync_when_sync_false(tmp_path):
    active = tmp_path / "RUNS_ACTIVE"
    storage = FsStorage(str(active))
    _seed_active_run(active, ACT_DIR)

    await storage.relocate_run(ACT_DIR, sync_data=False)

    # non-data files go to FINISHED, .hlo data diverted to NOSYNC
    finished = tmp_path / "RUNS_FINISHED" / ACT_DIR
    nosync = tmp_path / "RUNS_NOSYNC" / ACT_DIR
    assert (finished / f"{FIXED_UUID}.act").exists()
    assert not (finished / "dummy_act-data.hlo").exists()
    assert (nosync / "dummy_act-data.hlo").exists()


@pytest.mark.asyncio
async def test_relocate_run_noop_when_single_root(tmp_path):
    # save_root with no RUNS_ACTIVE segment -> finished_root == save_root -> no-op
    storage = FsStorage(str(tmp_path))
    run_dir = tmp_path / ACT_DIR
    run_dir.mkdir(parents=True)
    (run_dir / "a.act").write_text("x")
    await storage.relocate_run(ACT_DIR, sync_data=True)
    # nothing moved/removed
    assert (run_dir / "a.act").exists()


@pytest.mark.asyncio
async def test_relocate_run_missing_dir_is_noop(tmp_path):
    storage = FsStorage(str(tmp_path / "RUNS_ACTIVE"))
    # never created; must not raise
    await storage.relocate_run(ACT_DIR, sync_data=True)


@pytest.mark.asyncio
async def test_relocate_run_explicit_roots(tmp_path):
    active = tmp_path / "act"
    finished = tmp_path / "fin"
    storage = FsStorage(str(active), finished_root=str(finished))
    _seed_active_run(active, ACT_DIR)
    await storage.relocate_run(ACT_DIR, sync_data=True)
    assert not (active / ACT_DIR).exists()
    assert (finished / ACT_DIR / f"{FIXED_UUID}.act").exists()


# --- end-to-end: ActionSession.finish promotes the run dir ---------------------


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
        action_output_dir=ACT_DIR,
        save_act=True,
        save_data=True,
        action_status=[HloStatus.active],
    )
    kwargs.update(overrides)
    return RunAction(**kwargs)


def _session(storage, action):
    class _Wrap:
        def __init__(self, act):
            self.action = act

    return ActionSession(
        action,
        storage=storage,
        eventsink=FakeEventSink(),
        clock=FakeClock(),
        executor=Executor(active=_Wrap(action)),
        transport=FakeTransport(),
        now_factory=lambda: FINISH_NOW,
        uuid_factory=lambda: FIXED_UUID,
    )


@pytest.mark.asyncio
async def test_finish_promotes_run_dir_from_active_to_finished(tmp_path):
    active = tmp_path / "RUNS_ACTIVE"
    storage = FsStorage(str(active))
    action = _run_action()
    session = _session(storage, action)

    # myinit writes the .act meta into the active run dir
    await session.myinit()
    assert (active / ACT_DIR / f"{FIXED_UUID}.act").exists()

    await session.finish()

    # the whole run dir moved out of active into finished
    assert not (active / ACT_DIR).exists()
    assert (tmp_path / "RUNS_FINISHED" / ACT_DIR / f"{FIXED_UUID}.act").exists()


def test_finish_calls_relocate_run_once_per_nonmanual_action():
    storage = FakeStorage()
    action = _run_action()
    session = _session(storage, action)
    asyncio.run(session.finish())
    assert storage.run_relocations == [(ACT_DIR, True)]


def test_finish_propagates_sync_data_flag():
    storage = FakeStorage()
    action = _run_action(sync_data=False)
    session = _session(storage, action)
    asyncio.run(session.finish())
    assert storage.run_relocations == [(ACT_DIR, False)]


def test_finish_skips_relocate_for_manual_action():
    storage = FakeStorage()
    action = RunAction(action_name="manual_act", save_act=True, save_data=False)
    session = _session(storage, action)
    asyncio.run(session.promote_manual())
    asyncio.run(session.finish())
    assert storage.run_relocations == []


def test_finish_skips_relocate_when_save_act_false():
    storage = FakeStorage()
    action = _run_action(save_act=False, save_data=False)
    session = _session(storage, action)
    asyncio.run(session.finish())
    assert storage.run_relocations == []
