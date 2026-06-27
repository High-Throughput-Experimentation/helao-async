"""TDD tests for Task 1: domain meta helpers + action_session parity.

RED phase: these tests are written BEFORE the implementation.
They exercise:
1. The new pure helpers in lifecycle.py (run_kind, *_meta_relpath, hlo_relpath,
   meta_doc, active_relpath, finished_relpath).
2. The rewired ActionSession using real FsStorage, driving init+data+finish and
   asserting legacy-parity filenames/content and correct RUNS_ACTIVE->RUNS_FINISHED
   relocation (manual actions land under RUNS_DIAG and are never relocated).

Legacy reference: helao/core/servers/base.py:907-970 (write_act/exp/seq).
"""

import asyncio
import os
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
import ruamel.yaml

from helao.framework.domain.run_models import RunAction
from helao.framework.domain.executor import Executor
from helao.framework.domain.action_session import ActionSession
from helao.framework.domain import lifecycle

from helao.framework.adapters.fs_storage import FsStorage
from helao.framework.adapters.fakes.eventsink import FakeEventSink
from helao.framework.adapters.fakes.clock import FakeClock
from helao.framework.adapters.fakes.transport import FakeTransport

# --- fixtures -----------------------------------------------------------------

FIXED_NOW = datetime(2026, 6, 26, 17, 0, 0, 0)
FIXED_UUID = UUID("00000000-0000-0000-0000-000000000001")
FILE_CONN = UUID("00000000-0000-0000-0000-0000000000ff")

TS_STR = FIXED_NOW.strftime("%y%m%d.%H%M%S%f")  # "260626.170000000000"


def _ready_nonmanual_action():
    """Fully initialised non-manual RunAction with known timestamps."""
    a = RunAction(
        action_name="myact",
        action_uuid=FIXED_UUID,
        action_timestamp=FIXED_NOW,
        sequence_timestamp=FIXED_NOW,
        sequence_name="myseq",
        sequence_label="lab1",
        experiment_timestamp=FIXED_NOW,
        experiment_name="myexp",
        save_act=True,
        save_data=True,
        file_conn_keys=[FILE_CONN],
    )
    a.action_server.server_name = "srv"
    a.sequence_output_dir = lifecycle.sequence_output_dir(a)
    a.experiment_output_dir = lifecycle.experiment_output_dir(a)
    a.action_output_dir = lifecycle.action_output_dir(a)
    return a


# ===== Part 1: pure helpers in lifecycle.py ====================================


class TestRunKind:
    def test_non_manual_is_runs_active(self):
        a = _ready_nonmanual_action()
        assert lifecycle.run_kind(a) == "RUNS_ACTIVE"

    def test_manual_is_runs_diag(self):
        a = RunAction(action_name="m")
        a.manual_action = True
        assert lifecycle.run_kind(a) == "RUNS_DIAG"


class TestActionMetaRelpath:
    def test_correct_format_for_non_manual(self):
        a = _ready_nonmanual_action()
        rp = lifecycle.action_meta_relpath(a)
        # must be  RUNS_ACTIVE/<action_output_dir>/<ts>-act.yml
        ts = a.action_timestamp.strftime("%y%m%d.%H%M%S%f")
        out_dir = str(a.action_output_dir)
        assert rp == f"RUNS_ACTIVE/{out_dir}/{ts}-act.yml"

    def test_manual_lands_under_runs_diag(self):
        a = RunAction(action_name="m")
        a.manual_action = True
        a.action_timestamp = FIXED_NOW
        a.action_output_dir = "26.25/0622/0__0__srv__m"
        ts = FIXED_NOW.strftime("%y%m%d.%H%M%S%f")
        rp = lifecycle.action_meta_relpath(a)
        assert rp.startswith("RUNS_DIAG/")
        assert rp.endswith(f"{ts}-act.yml")


class TestExperimentMetaRelpath:
    def test_correct_format(self):
        a = _ready_nonmanual_action()
        rp = lifecycle.experiment_meta_relpath(a)
        ts = a.experiment_timestamp.strftime("%y%m%d.%H%M%S%f")
        out_dir = str(a.experiment_output_dir)
        assert rp == f"RUNS_ACTIVE/{out_dir}/{ts}-exp.yml"


class TestSequenceMetaRelpath:
    def test_correct_format(self):
        a = _ready_nonmanual_action()
        rp = lifecycle.sequence_meta_relpath(a)
        ts = a.sequence_timestamp.strftime("%y%m%d.%H%M%S%f")
        out_dir = str(a.sequence_output_dir)
        assert rp == f"RUNS_ACTIVE/{out_dir}/{ts}-seq.yml"


class TestHloRelpath:
    def test_prefixes_run_kind_to_action_output_dir(self):
        a = _ready_nonmanual_action()
        leaf = "myact-someuuid.hlo"
        rp = lifecycle.hlo_relpath(a, leaf)
        out_dir = str(a.action_output_dir)
        assert rp == f"RUNS_ACTIVE/{out_dir}/{leaf}"

    def test_manual_uses_runs_diag(self):
        a = RunAction(action_name="m")
        a.manual_action = True
        a.action_output_dir = "26.25/0622/0__0__srv__m"
        rp = lifecycle.hlo_relpath(a, "m-x.hlo")
        assert rp.startswith("RUNS_DIAG/")


class TestMetaDoc:
    def test_file_type_is_first_key(self):
        doc = lifecycle.meta_doc("action", {"a": 1, "b": 2})
        keys = list(doc.keys())
        assert keys[0] == "file_type"
        assert doc["file_type"] == "action"

    def test_body_merged_in(self):
        doc = lifecycle.meta_doc("experiment", {"x": 99})
        assert doc["x"] == 99
        assert doc["file_type"] == "experiment"


class TestActiveFinishedRelpath:
    def test_active_relpath(self):
        out_dir = "26.25/0622/seq/exp/act"
        assert lifecycle.active_relpath(out_dir) == f"RUNS_ACTIVE/{out_dir}"

    def test_finished_relpath(self):
        out_dir = "26.25/0622/seq/exp/act"
        assert lifecycle.finished_relpath(out_dir) == f"RUNS_FINISHED/{out_dir}"


# ===== Part 2: ActionSession integration with real FsStorage ===================
# These drive a session through init+data+finish and assert on-disk state.


def _make_session_with_fs(tmp_dir, action, finish_at=FIXED_NOW):
    storage = FsStorage(save_root=str(tmp_dir))

    class _Wrap:
        def __init__(self, act):
            self.action = act

    executor = Executor(active=_Wrap(action))
    session = ActionSession(
        action,
        storage=storage,
        eventsink=FakeEventSink(),
        clock=FakeClock(),
        executor=executor,
        transport=FakeTransport(),
        now_factory=lambda: finish_at,
        uuid_factory=lambda: FIXED_UUID,
    )
    return session, storage


def _run_init_data_finish(tmp_path, action):
    """Run myinit + open_file + finish in a single event loop (avoids aiofiles loop-closed issue)."""
    session, storage = _make_session_with_fs(tmp_path, action)

    async def _go():
        await session.myinit()
        await session.open_file(FILE_CONN, header="epoch_ns: 1")
        await session.finish()

    asyncio.run(_go())
    return session, storage


def _run_init_finish(tmp_path, action):
    """Run myinit + finish in a single event loop."""
    session, storage = _make_session_with_fs(tmp_path, action)

    async def _go():
        await session.myinit()
        await session.finish()

    asyncio.run(_go())
    return session, storage


def _run_only_myinit(tmp_path, action):
    """Run only myinit in a single event loop."""
    session, storage = _make_session_with_fs(tmp_path, action)
    asyncio.run(session.myinit())
    return session, storage


def _run_only_open_file(tmp_path, action):
    """Run only open_file in a single event loop."""
    session, storage = _make_session_with_fs(tmp_path, action)
    asyncio.run(session.open_file(FILE_CONN, header="epoch_ns: 1"))
    return session, storage


class TestNonManualSessionArtifacts:
    """A non-manual action should land under RUNS_ACTIVE, then relocate to RUNS_FINISHED."""

    def test_act_yml_exists_in_runs_active_after_init(self, tmp_path):
        a = _ready_nonmanual_action()
        _run_only_myinit(tmp_path, a)
        # act meta should exist under RUNS_ACTIVE
        ts = a.action_timestamp.strftime("%y%m%d.%H%M%S%f")
        out_dir = str(a.action_output_dir)
        expected = tmp_path / "RUNS_ACTIVE" / out_dir / f"{ts}-act.yml"
        assert expected.exists(), f"Expected {expected} to exist after myinit"

    def test_act_yml_has_file_type_action_key(self, tmp_path):
        a = _ready_nonmanual_action()
        _run_only_myinit(tmp_path, a)
        ts = a.action_timestamp.strftime("%y%m%d.%H%M%S%f")
        out_dir = str(a.action_output_dir)
        yf = tmp_path / "RUNS_ACTIVE" / out_dir / f"{ts}-act.yml"
        yaml = ruamel.yaml.YAML(typ="safe")
        doc = yaml.load(yf.read_text())
        assert doc.get("file_type") == "action", f"file_type missing or wrong: {doc}"

    def test_hlo_file_exists_under_runs_active(self, tmp_path):
        a = _ready_nonmanual_action()
        _run_only_open_file(tmp_path, a)
        out_dir = str(a.action_output_dir)
        expected = tmp_path / "RUNS_ACTIVE" / out_dir / f"myact-{FILE_CONN}.hlo"
        assert expected.exists(), f"Expected HLO at {expected}"

    def test_finish_moves_tree_to_runs_finished(self, tmp_path):
        a = _ready_nonmanual_action()
        _run_init_data_finish(tmp_path, a)
        out_dir = str(a.action_output_dir)
        finished_dir = tmp_path / "RUNS_FINISHED" / out_dir
        active_dir = tmp_path / "RUNS_ACTIVE" / out_dir
        assert finished_dir.exists(), f"RUNS_FINISHED tree missing: {finished_dir}"
        assert not active_dir.exists(), f"RUNS_ACTIVE tree should be gone: {active_dir}"

    def test_finish_act_yml_under_runs_finished_has_file_type(self, tmp_path):
        a = _ready_nonmanual_action()
        _run_init_finish(tmp_path, a)
        out_dir = str(a.action_output_dir)
        # After relocation the tree is under RUNS_FINISHED
        finished_dir = tmp_path / "RUNS_FINISHED" / out_dir
        ymls = list(finished_dir.glob("*-act.yml"))
        assert ymls, "No *-act.yml found in RUNS_FINISHED tree"
        yaml = ruamel.yaml.YAML(typ="safe")
        doc = yaml.load(ymls[0].read_text())
        assert doc.get("file_type") == "action"


def _run_manual_init_finish(tmp_path):
    """Create a manual action, promote it, run myinit+finish in a single loop."""
    a = RunAction(action_name="manual_act", save_act=True, save_data=False)
    session, storage = _make_session_with_fs(tmp_path, a)

    async def _go():
        await session.promote_manual()
        await session.myinit()
        await session.finish()

    asyncio.run(_go())
    return session, storage, a


def _run_manual_only_init(tmp_path):
    """Create a manual action, promote it, run myinit only in a single loop."""
    a = RunAction(action_name="manual_act", save_act=True, save_data=False)
    session, storage = _make_session_with_fs(tmp_path, a)

    async def _go():
        await session.promote_manual()
        await session.myinit()

    asyncio.run(_go())
    return session, storage, a


class TestManualSessionArtifacts:
    """A manual action should land under RUNS_DIAG and never be relocated."""

    def test_manual_act_yml_under_runs_diag(self, tmp_path):
        _run_manual_only_init(tmp_path)
        # should exist under RUNS_DIAG, NOT RUNS_ACTIVE
        diag_files = list((tmp_path / "RUNS_DIAG").rglob("*-act.yml"))
        active_files = list((tmp_path / "RUNS_ACTIVE").rglob("*-act.yml")) if (tmp_path / "RUNS_ACTIVE").exists() else []
        assert diag_files, f"Expected *-act.yml under RUNS_DIAG, got none"
        assert not active_files, f"Manual act should NOT be in RUNS_ACTIVE"

    def test_manual_finish_does_not_create_runs_finished(self, tmp_path):
        _run_manual_init_finish(tmp_path)
        # RUNS_FINISHED should not exist (or have no act dirs)
        rf = tmp_path / "RUNS_FINISHED"
        assert not rf.exists() or not any(rf.rglob("*")), \
            "Manual action must not create RUNS_FINISHED artifacts"

    def test_manual_exp_seq_meta_under_runs_diag(self, tmp_path):
        _run_manual_init_finish(tmp_path)
        diag_exp = list((tmp_path / "RUNS_DIAG").rglob("*-exp.yml"))
        diag_seq = list((tmp_path / "RUNS_DIAG").rglob("*-seq.yml"))
        assert diag_exp, "Expected *-exp.yml under RUNS_DIAG"
        assert diag_seq, "Expected *-seq.yml under RUNS_DIAG"

    def test_manual_exp_seq_meta_has_file_type(self, tmp_path):
        _run_manual_init_finish(tmp_path)
        yaml = ruamel.yaml.YAML(typ="safe")
        for pattern, kind in [("*-exp.yml", "experiment"), ("*-seq.yml", "sequence")]:
            files = list((tmp_path / "RUNS_DIAG").rglob(pattern))
            assert files, f"No {pattern} found"
            doc = yaml.load(files[0].read_text())
            assert doc.get("file_type") == kind, f"{pattern}: file_type wrong: {doc}"


class TestConnRelpathUsesRunKind:
    """_conn_relpath must include the RUNS_ACTIVE prefix (for FsStorage rooted at config root)."""

    def test_conn_relpath_starts_with_runs_active(self):
        a = _ready_nonmanual_action()
        # Use FakeStorage here since _conn_relpath is pure (no I/O needed)
        from helao.framework.adapters.fakes.storage import FakeStorage
        from helao.framework.adapters.fakes.eventsink import FakeEventSink
        from helao.framework.adapters.fakes.clock import FakeClock
        from helao.framework.adapters.fakes.transport import FakeTransport

        class _Wrap:
            def __init__(self, act):
                self.action = act

        session = ActionSession(
            a,
            storage=FakeStorage(),
            eventsink=FakeEventSink(),
            clock=FakeClock(),
            executor=Executor(active=_Wrap(a)),
            transport=FakeTransport(),
        )
        rp = session._conn_relpath(FILE_CONN)
        assert rp.startswith("RUNS_ACTIVE/"), f"Got: {rp}"

    def test_conn_relpath_ends_with_hlo_leaf(self):
        a = _ready_nonmanual_action()
        from helao.framework.adapters.fakes.storage import FakeStorage
        from helao.framework.adapters.fakes.eventsink import FakeEventSink
        from helao.framework.adapters.fakes.clock import FakeClock
        from helao.framework.adapters.fakes.transport import FakeTransport

        class _Wrap:
            def __init__(self, act):
                self.action = act

        session = ActionSession(
            a,
            storage=FakeStorage(),
            eventsink=FakeEventSink(),
            clock=FakeClock(),
            executor=Executor(active=_Wrap(a)),
            transport=FakeTransport(),
        )
        rp = session._conn_relpath(FILE_CONN)
        assert rp.endswith(f"myact-{FILE_CONN}.hlo"), f"Got: {rp}"
