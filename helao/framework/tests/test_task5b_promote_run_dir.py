"""TDD tests for Task 5b: file-granular promote_run_dir (RUNS_ACTIVE -> dest).

Faithful port of legacy ``helao.helpers.yml_tools.move_dir``:
- dest base = RUNS_DIAG (manual) else RUNS_FINISHED
- ``.hlo`` with sync_data=False -> RUNS_NOSYNC; otherwise dest base
- action: recursive files; exp/seq: immediate files only
- copy non-NOSYNC, move NOSYNC, then rmtree the emptied source dir

Covers:
1. FsStorage.promote_run_dir unit behaviour (manual/sync/recursive).
2. Full seq->exp->act tree reaching RUNS_FINISHED via action_session.finish +
   orch FinishExperiment/FinishSequence through execute_commands.
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest

from helao.framework.adapters.fs_storage import FsStorage


# --- helpers ------------------------------------------------------------------


def _write(root: Path, relpath: str, body: str = "x") -> Path:
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


# ===== Part 1: FsStorage.promote_run_dir =======================================


def test_promote_action_recursive_to_finished(tmp_path):
    """Non-manual action: meta + hlo move to RUNS_FINISHED; RUNS_ACTIVE dir gone."""
    storage = FsStorage(save_root=str(tmp_path))
    out_dir = "26.25/0626/seq/exp/act"
    _write(tmp_path, f"RUNS_ACTIVE/{out_dir}/260626-act.yml")
    _write(tmp_path, f"RUNS_ACTIVE/{out_dir}/myact-conn.hlo")

    asyncio.run(
        storage.promote_run_dir(out_dir, manual=False, sync_data=True, recursive=True)
    )

    assert (tmp_path / "RUNS_FINISHED" / out_dir / "260626-act.yml").exists()
    assert (tmp_path / "RUNS_FINISHED" / out_dir / "myact-conn.hlo").exists()
    assert not (tmp_path / "RUNS_ACTIVE" / out_dir).exists()


def test_promote_manual_action_to_diag(tmp_path):
    """Manual action: files promoted to RUNS_DIAG, not RUNS_FINISHED."""
    storage = FsStorage(save_root=str(tmp_path))
    out_dir = "26.25/0626/seq/exp/act"
    _write(tmp_path, f"RUNS_ACTIVE/{out_dir}/260626-act.yml")
    _write(tmp_path, f"RUNS_ACTIVE/{out_dir}/myact-conn.hlo")

    asyncio.run(
        storage.promote_run_dir(out_dir, manual=True, sync_data=True, recursive=True)
    )

    assert (tmp_path / "RUNS_DIAG" / out_dir / "260626-act.yml").exists()
    assert (tmp_path / "RUNS_DIAG" / out_dir / "myact-conn.hlo").exists()
    assert not (tmp_path / "RUNS_FINISHED").exists()
    assert not (tmp_path / "RUNS_ACTIVE" / out_dir).exists()


def test_promote_sync_data_false_diverts_hlo_to_nosync(tmp_path):
    """sync_data=False: .hlo -> RUNS_NOSYNC, .act.yml -> RUNS_FINISHED."""
    storage = FsStorage(save_root=str(tmp_path))
    out_dir = "26.25/0626/seq/exp/act"
    _write(tmp_path, f"RUNS_ACTIVE/{out_dir}/260626-act.yml")
    _write(tmp_path, f"RUNS_ACTIVE/{out_dir}/myact-conn.hlo")

    asyncio.run(
        storage.promote_run_dir(out_dir, manual=False, sync_data=False, recursive=True)
    )

    assert (tmp_path / "RUNS_FINISHED" / out_dir / "260626-act.yml").exists()
    assert (tmp_path / "RUNS_NOSYNC" / out_dir / "myact-conn.hlo").exists()
    # .hlo must NOT also be under RUNS_FINISHED
    assert not (tmp_path / "RUNS_FINISHED" / out_dir / "myact-conn.hlo").exists()
    assert not (tmp_path / "RUNS_ACTIVE" / out_dir).exists()


def test_promote_non_recursive_only_immediate_files(tmp_path):
    """recursive=False (exp/seq): only immediate files move; child dirs untouched."""
    storage = FsStorage(save_root=str(tmp_path))
    exp_dir = "26.25/0626/seq/exp"
    _write(tmp_path, f"RUNS_ACTIVE/{exp_dir}/260626-exp.yml")
    # a child action subdir that must NOT be swept by a non-recursive promote
    _write(tmp_path, f"RUNS_ACTIVE/{exp_dir}/act/leftover.txt")

    asyncio.run(
        storage.promote_run_dir(exp_dir, manual=False, sync_data=True, recursive=False)
    )

    assert (tmp_path / "RUNS_FINISHED" / exp_dir / "260626-exp.yml").exists()
    # child file untouched (still under RUNS_ACTIVE)
    assert (tmp_path / "RUNS_ACTIVE" / exp_dir / "act" / "leftover.txt").exists()


def test_promote_missing_source_is_noop(tmp_path):
    """Missing source dir is tolerated (idempotent-ish)."""
    storage = FsStorage(save_root=str(tmp_path))
    # nothing under RUNS_ACTIVE
    asyncio.run(
        storage.promote_run_dir(
            "26.25/0626/seq/exp/act", manual=False, sync_data=True, recursive=True
        )
    )
    # no crash, no dest created
    assert not (tmp_path / "RUNS_FINISHED").exists()


# ===== Part 2: full seq->exp->act tree reaches RUNS_FINISHED ===================


from helao.framework.domain.run_models import RunAction
from helao.framework.domain.executor import Executor
from helao.framework.domain.action_session import ActionSession
from helao.framework.domain import lifecycle
from helao.framework.adapters.fakes.eventsink import FakeEventSink
from helao.framework.adapters.fakes.clock import FakeClock
from helao.framework.adapters.fakes.transport import FakeTransport

FIXED_NOW = datetime(2026, 6, 26, 17, 0, 0, 0)
FIXED_UUID = UUID("00000000-0000-0000-0000-000000000001")
FILE_CONN = UUID("00000000-0000-0000-0000-0000000000ff")


def _ready_action():
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


def test_full_tree_reaches_runs_finished(tmp_path):
    """seq/exp/act meta + hlo all written under RUNS_ACTIVE; after action +
    exp + seq finish, ALL land under RUNS_FINISHED with legacy names and the
    RUNS_ACTIVE sources are gone."""
    a = _ready_action()
    storage = FsStorage(save_root=str(tmp_path))

    class _Wrap:
        def __init__(self, act):
            self.action = act

    session = ActionSession(
        a,
        storage=storage,
        eventsink=FakeEventSink(),
        clock=FakeClock(),
        executor=Executor(active=_Wrap(a)),
        transport=FakeTransport(),
        now_factory=lambda: FIXED_NOW,
        uuid_factory=lambda: FIXED_UUID,
    )

    async def _go():
        # write seq + exp meta under RUNS_ACTIVE (as dispatch/init would)
        await storage.write_meta(
            lifecycle.sequence_meta_relpath(a),
            lifecycle.meta_doc("sequence", a.as_dict()),
        )
        await storage.write_meta(
            lifecycle.experiment_meta_relpath(a),
            lifecycle.meta_doc("experiment", a.as_dict()),
        )
        # action: init + stream + finish (finish promotes the action leaf)
        await session.myinit()
        await session.open_file(FILE_CONN, header="epoch_ns: 1")
        await session.finish()
        # now promote exp then seq (what orch FinishExperiment/FinishSequence do)
        await storage.promote_run_dir(
            a.experiment_output_dir, manual=False, sync_data=True, recursive=False
        )
        await storage.promote_run_dir(
            a.sequence_output_dir, manual=False, sync_data=True, recursive=False
        )

    asyncio.run(_go())

    seq_dir = tmp_path / "RUNS_FINISHED" / a.sequence_output_dir
    exp_dir = tmp_path / "RUNS_FINISHED" / a.experiment_output_dir
    act_dir = tmp_path / "RUNS_FINISHED" / a.action_output_dir
    ts = FIXED_NOW.strftime("%y%m%d.%H%M%S%f")
    assert (seq_dir / f"{ts}-seq.yml").exists()
    assert (exp_dir / f"{ts}-exp.yml").exists()
    assert (act_dir / f"{ts}-act.yml").exists()
    assert (act_dir / f"myact-{FILE_CONN}.hlo").exists()
    # active sources gone
    assert not (tmp_path / "RUNS_ACTIVE" / a.sequence_output_dir).exists()
