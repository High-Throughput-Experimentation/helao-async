"""Startup reconciliation of actions an earlier process left ``[active]``.

An action server that ends while an action runs (graceful stop, hot reload,
kill) never rewrites that action's ``-act.yml``, so it reads ``active`` for
ever and the syncer refuses to ship the parent experiment. Every ``active``
line in a server's *own* run-state journal at startup is stale by
construction, so ``ActionHost.reconcile_interrupted`` finishes those records
(``[finished, errored]``), then hands them to the syncer through ``move_dir``.

The host is a real ``ActionHost`` with the real native meta writer; the only
stub is the syncer handoff (``yml_finisher``), except in the test that points
the host at a closed port to prove an unreachable syncer cannot raise.
"""

# Port stubs and Optional host attributes are deliberate in a test double.
# pyright: reportArgumentType=false, reportOptionalMemberAccess=false, reportOperatorIssue=false

import asyncio
import os
import socket
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest

import helao.helpers.yml_tools as yml_tools_module
from helao.hexagon.adapters.native.sync_driver import HelaoYml, SyncDriver
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.helpers.premodels import Action
from helao.helpers.run_state import record_active
from helao.helpers.yml_tools import yml_load
from helao.hexagon.tests.sync_fixtures import mk_uuid, write_yml

EXP_DIR = "26.23/0610/seq_dir/exp_dir"


class _Stub:
    def __getattr__(self, name):
        raise AssertionError(f"port member {name!r} used unexpectedly")


class _Clock:
    def now_ns(self):
        return 0

    def offset(self):
        return 0.0


def _host(sync_port=None, key="SIM", root=None):
    from helao.hexagon.adapters.native.artifact_store import NativeArtifactStoreAdapter
    from helao.hexagon.app.action_host import ActionHost
    from helao.hexagon.app.wiring import PortWiring

    servers = {key: {"host": "127.0.0.1", "port": 8002, "params": {}}}
    if sync_port is not None:
        servers["SYNC"] = {"host": "127.0.0.1", "port": sync_port, "group": "action"}
    return ActionHost(
        server_key=key,
        server_title=key,
        description="reconcile test",
        version=1.0,
        wiring=PortWiring(
            config=_Stub(),
            logging=_Stub(),
            clock=_Clock(),
            state_persistence=_Stub(),
            health=_Stub(),
            artifact_store=NativeArtifactStoreAdapter(config=_Stub(), clock=_Clock()),
        ),
        helao_cfg={
            "root": root or tempfile.mkdtemp(prefix="helao_reconcile_"),
            "servers": servers,
        },
    )


def _action(order: int, manual: bool = False) -> Action:
    act = Action(
        action_name="acquire_data",
        action_server=MachineModel(server_name="SIM", machine_name="m"),
        orch_submit_order=order,
        experiment_uuid=UUID(mk_uuid(500)),
    )
    if not manual:
        act.sequence_timestamp = act.experiment_timestamp = None
        from helao.helpers.time_utils import set_time

        act.sequence_timestamp = set_time()
        act.experiment_timestamp = set_time()
        act.experiment_output_dir = Path(EXP_DIR)
    act.action_uuid = UUID(mk_uuid(order))
    act.init_act()
    return act


async def _journalled(host, act: Action, statuses) -> Path:
    """Write ``act`` with ``statuses`` and journal it ``active``; return its yml."""
    from helao.core.models.run_dir import redirect_manual_dir

    act.action_status = list(statuses)
    await host.write_act(act)
    save_root = str(host.helaodirs.save_root)
    if act.manual_action:
        save_root = redirect_manual_dir(save_root)
    act_dir = Path(save_root) / act.action_output_dir
    record_active(host, "action", act.action_uuid, act_dir, parent=act.experiment_uuid)
    (yml,) = act_dir.glob("*-act.json")
    return yml


@pytest.fixture
def finish_calls(monkeypatch):
    """Stub the syncer handoff and record what it was asked to finish."""
    calls = []

    async def fake_finisher(yml_path, sync_config=None, retry=3):
        assert Path(yml_path).is_file(), f"handoff names a missing file: {yml_path}"
        calls.append(yml_path)
        return True

    monkeypatch.setattr(yml_tools_module, "yml_finisher", fake_finisher)
    return calls


def _statuses(yml: Path) -> list:
    return [str(s).split(".")[-1] for s in yml_load(str(yml))["action_status"]]


async def _fixture_world(host):
    """(a) active/active, (b) active journal/finished yml, (c) manual, (d) missing dir."""
    a = await _journalled(host, _action(1), [HloStatus.active])
    b = await _journalled(host, _action(2), [HloStatus.finished])
    c = await _journalled(host, _action(3, manual=True), [HloStatus.active])
    d_act = _action(4)
    record_active(
        host,
        "action",
        d_act.action_uuid,
        Path(host.helaodirs.save_root) / d_act.action_output_dir,
        parent=d_act.experiment_uuid,
    )
    return a, b, c, d_act


@pytest.mark.asyncio
async def test_interrupted_actions_are_finished_and_handed_off(
    finish_calls, monkeypatch
):
    from helao.hexagon.app import action_host as ah

    warnings = []
    monkeypatch.setattr(ah.LOGGER, "warning", lambda m, *a, **k: warnings.append(m))
    host = _host()
    a, b, c, d_act = await _fixture_world(host)
    b_bytes = b.read_bytes()
    # the orchestrator's records are not this server's to touch
    host.run_journal.append(mk_uuid(900), "experiment", "active", EXP_DIR)
    with host.status_q.queue_context() as q:
        done = await host.reconcile_interrupted()
        assert q.empty(), "reconcile must never broadcast on status_q"

    # (a) rewritten as an errored, finished record with a code and a message
    assert _statuses(a) == ["finished", "errored"]
    meta = yml_load(str(a))
    assert str(meta["error_code"]).split(".")[-1] == ErrorCodes.critical_error.value
    assert (
        "stopped while the action was running" in meta["action_output"]["error_message"]
    )
    assert meta["action_finished_timestamp"]
    # (b) already terminal: not rewritten
    assert b.read_bytes() == b_bytes
    # journal: every action entry is evicted, the experiment entry is not
    assert list(host.run_journal.working_set()) == [mk_uuid(900)]
    # handoff: a and b go to SYNC, the manual record (c) does not
    assert sorted(Path(p).parent.name for p in finish_calls) == sorted(
        [a.parent.name, b.parent.name]
    )
    assert _statuses(c) == ["finished", "errored"]
    # (d) missing directory evicted with a warning, not a crash
    assert str(d_act.action_uuid) in done
    assert any("no -act record" in m for m in warnings)


@pytest.mark.asyncio
async def test_second_run_is_a_noop(finish_calls):
    host = _host()
    a, *_ = await _fixture_world(host)
    await host.reconcile_interrupted()
    snapshot = a.read_bytes()
    n_calls = len(finish_calls)
    again = await host.reconcile_interrupted()
    assert again == []
    assert a.read_bytes() == snapshot
    assert len(finish_calls) == n_calls


@pytest.mark.asyncio
async def test_live_actions_are_left_alone(finish_calls):
    host = _host()
    a = await _journalled(host, _action(1), [HloStatus.active])
    host.actives[UUID(mk_uuid(1))] = object()
    await host.reconcile_interrupted()
    assert _statuses(a) == ["active"]
    assert finish_calls == []


@pytest.mark.asyncio
async def test_unreachable_syncer_does_not_raise():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # nothing listens here: connection refused
    host = _host(sync_port=port)
    a = await _journalled(host, _action(1), [HloStatus.active])
    done = await host.reconcile_interrupted()
    assert done == [mk_uuid(1)]
    assert _statuses(a) == ["finished", "errored"]


@pytest.mark.asyncio
async def test_unreadable_yml_and_corrupt_journal_never_raise(finish_calls):
    host = _host()
    a = await _journalled(host, _action(1), [HloStatus.active])
    a.write_text("{{{ not yaml", encoding="utf-8")
    assert await host.reconcile_interrupted() == []
    # a corrupt journal (bad line followed by a good one) is logged, not raised
    host.run_journal.path.write_text('not json\n{"uuid":"x"}\n', encoding="utf-8")
    assert await host.reconcile_interrupted() == []


@pytest.mark.asyncio
async def test_startup_schedules_reconcile_in_background(finish_calls):
    host = _host()
    a = await _journalled(host, _action(1), [HloStatus.active])
    startup = next(f for f in host.router.on_startup if f.__name__ == "startup_event")
    startup()  # returns before the reconcile has run: it is a background task
    assert host.reconcile_task is not None
    assert _statuses(a) == ["active"]
    await host.reconcile_task
    assert _statuses(a) == ["finished", "errored"]


@pytest.mark.asyncio
async def test_reconciled_child_no_longer_blocks_the_parent_sync_gate(finish_calls):
    """sync_driver blocks a parent on non-estopped ``active`` children."""
    host = _host()
    root = Path(host.helaodirs.root)
    exp_yml = root / "RUNS" / EXP_DIR / "260610.120000000100-exp.yml"
    write_yml(
        exp_yml,
        {
            "experiment_uuid": mk_uuid(500),
            "experiment_name": "e",
            "sequence_uuid": mk_uuid(999),
        },
    )
    a = await _journalled(host, _action(1), [HloStatus.active])
    before = [c for c in HelaoYml(exp_yml).active_children if not c.is_estopped]
    assert before, "fixture is vacuous: the stale child must block first"
    await host.reconcile_interrupted()
    exp = HelaoYml(exp_yml)
    assert [c for c in exp.active_children if not c.is_estopped] == []
    assert [c.target for c in exp.finished_children] == [a]


@pytest.mark.asyncio
async def test_syncer_startup_sweep_would_find_the_reconciled_record(finish_calls):
    """Fallback when /finish_yml is refused: list_pending_acts globs the yml."""
    host = _host()
    a = await _journalled(host, _action(1), [HloStatus.active])
    await host.reconcile_interrupted()
    drv = SyncDriver.__new__(SyncDriver)
    drv.helaodirs = host.helaodirs
    assert [Path(p) for p in drv.list_pending_acts()] == [a]


# --- fix round 1 --------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_active_state_entries_are_reconciled(finish_calls):
    """A key's journal can be shared (the syncer's UNSYNCED lines); leave those."""
    from helao.helpers.run_state import UNSYNCED

    host = _host()
    a = await _journalled(host, _action(1), [HloStatus.active])
    host.run_journal.append(
        str(UUID(mk_uuid(1))),
        "action",
        UNSYNCED,
        a.parent.relative_to(host.helaodirs.root).as_posix(),
    )
    assert await host.reconcile_interrupted() == []
    assert _statuses(a) == ["active"]
    assert finish_calls == []
    assert list(host.run_journal.working_set()) == [mk_uuid(1)]


@pytest.mark.asyncio
async def test_other_servers_actions_in_a_shared_journal_are_left_alone(finish_calls):
    """Reproduces the SYNC key collision: its journal lists other servers' acts."""
    host = _host(key="SYNC")
    foreign = await _journalled(host, _action(1), [HloStatus.active])  # owner SIM
    own = _action(2)
    own.action_server = MachineModel(server_name="SYNC", machine_name="m")
    own.action_output_dir = None
    own.init_act(force=True)
    own.action_uuid = UUID(mk_uuid(2))
    mine = await _journalled(host, own, [HloStatus.active])
    done = await host.reconcile_interrupted()
    assert done == [mk_uuid(2)]
    assert _statuses(foreign) == ["active"]
    assert _statuses(mine) == ["finished", "errored"]
    assert list(host.run_journal.working_set()) == [mk_uuid(1)]


@pytest.mark.asyncio
async def test_partial_data_files_are_registered_so_the_syncer_ships_them(
    finish_calls,
):
    host = _host()
    a = await _journalled(host, _action(1), [HloStatus.active])
    d = a.parent
    (d / "acq-1.0.0.0.0__0.hlo").write_text("{}\n1 2\n", encoding="utf-8")
    (d / "extra.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (d / ".deadbeef.tmp").write_text("x", encoding="utf-8")
    (d / ".hidden").write_text("x", encoding="utf-8")
    newest = d / "acq-1.0.0.0.0__0.hlo"
    os.utime(newest, (4102444800, 4102444800))  # 2100-01-01
    await host.reconcile_interrupted()
    shipped = sorted(p.name for p in HelaoYml(a).upload_files)
    assert shipped == ["acq-1.0.0.0.0__0.hlo", "extra.csv"]
    meta = yml_load(str(a))
    assert meta["action_finished_timestamp"] == datetime.fromtimestamp(
        4102444800
    ).strftime("%Y-%m-%d %H:%M:%S.%f")
    types = {f["file_name"]: f["file_type"] for f in meta["files"]}
    assert types["acq-1.0.0.0.0__0.hlo"] == "sim_helao__file"


@pytest.mark.asyncio
async def test_a_second_process_for_the_same_key_skips_reconcile(finish_calls):
    first = _host()
    root = first.helaodirs.root
    second = _host(root=str(root))
    a = await _journalled(first, _action(1), [HloStatus.active])
    first.aloop = second.aloop = asyncio.get_running_loop()
    first.start_reconcile()
    assert first.reconcile_task is not None
    second.start_reconcile()
    assert second.reconcile_task is None, "second host must not reconcile"
    await first.reconcile_task
    assert _statuses(a) == ["finished", "errored"]
    first._unlock_server_key()
    second.start_reconcile()  # the lock is free once the first process is gone
    assert second.reconcile_task is not None
    second._unlock_server_key()


@pytest.mark.asyncio
async def test_a_failing_reconcile_task_is_logged(finish_calls, monkeypatch):
    from helao.hexagon.app import action_host as ah

    errors = []
    monkeypatch.setattr(ah.LOGGER, "error", lambda m, *a, **k: errors.append(m))
    host = _host()

    async def boom():
        raise RuntimeError("boom")

    host.reconcile_interrupted = boom
    host.aloop = asyncio.get_running_loop()
    host.start_reconcile()
    assert host.reconcile_task is not None
    await asyncio.gather(host.reconcile_task, return_exceptions=True)
    await asyncio.sleep(0)
    assert any("Reconcile of interrupted actions failed" in m for m in errors)
    host._unlock_server_key()


def _as_record(path: Path, ext: str) -> Path:
    """Re-store the record at ``path`` as ``<stem><ext>``; drop the original."""
    from helao.helpers.meta_io import dumps_meta, read_meta

    target = path.with_suffix(ext)
    text = dumps_meta(read_meta(path), target)
    path.unlink()
    target.write_text(text, encoding="utf-8")
    return target


def _act_records(act_dir: Path) -> list:
    return sorted(p.name for p in act_dir.iterdir() if "-act." in p.name)


@pytest.mark.asyncio
@pytest.mark.parametrize("ext", [".json", ".yml"])
async def test_reconcile_rewrites_the_record_in_its_own_format(finish_calls, ext):
    """The in-flight rule on the reconcile path: an ``-act.json`` is rewritten in
    place, and a legacy ``-act.yml`` begun before the upgrade stays YAML. Neither
    gains a twin, and the syncer handoff names the file actually rewritten."""
    host = _host()
    rec = _as_record(await _journalled(host, _action(1), [HloStatus.active]), ext)
    await host.reconcile_interrupted()
    assert _act_records(rec.parent) == [rec.name]
    assert _statuses(rec) == ["finished", "errored"]
    assert finish_calls == [str(rec)]
