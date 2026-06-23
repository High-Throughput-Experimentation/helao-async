import asyncio
from pathlib import Path
from helao.framework.adapters.fakes.sync_storage import FakeSyncStorage
from helao.framework.domain.sync.sync_models import HelaoYml, Progress, SyncJob
from helao.framework.domain.sync.sync_logic import SyncEngine

_FINISHED = Path("/runs/RUNS_FINISHED")
_SYNCED = Path("/runs/RUNS_SYNCED")


def _config():
    return {
        "use_s3": False,
        "s3_prefix": "bucket/prefix",
        "runs_finished_root": _FINISHED,
        "runs_synced_root": _SYNCED,
    }


def _act_path():
    return _FINISHED / "seq1" / "exp1" / "act1" / "20240101T120000_uuid-act.yml"


def _exp_path():
    return _FINISHED / "seq1" / "exp1" / "20240101T120001_uuid-exp.yml"


def _seq_path():
    return _FINISHED / "seq1" / "20240101T120002_uuid-seq.yml"


# ── list_pending ──────────────────────────────────────────────────────────────

def test_list_pending_returns_only_seqs():
    store = FakeSyncStorage()
    store.add_yml(_seq_path())
    store.add_yml(_exp_path())
    store.add_yml(_act_path())
    engine = SyncEngine(store, _config())
    jobs = engine.list_pending()
    assert len(jobs) == 1
    assert jobs[0].yml.type == "sequence"


def test_list_pending_acts():
    store = FakeSyncStorage()
    store.add_yml(_act_path())
    store.add_yml(_seq_path())
    engine = SyncEngine(store, _config())
    jobs = engine.list_pending_acts()
    assert len(jobs) == 1
    assert jobs[0].yml.type == "action"


def test_list_pending_exps():
    store = FakeSyncStorage()
    store.add_yml(_exp_path())
    store.add_yml(_seq_path())
    engine = SyncEngine(store, _config())
    jobs = engine.list_pending_exps()
    assert len(jobs) == 1
    assert jobs[0].yml.type == "experiment"


def test_list_pending_omits_manual():
    store = FakeSyncStorage()
    manual = _FINISHED / "manual_orch_seq_20240101" / "20240101T120000_uuid-seq.yml"
    store.add_yml(manual)
    store.add_yml(_seq_path())
    engine = SyncEngine(store, _config())
    assert len(engine.list_pending(omit_manual=True)) == 1
    assert len(engine.list_pending(omit_manual=False)) == 2


# ── sync_one ──────────────────────────────────────────────────────────────────

def test_sync_one_act_calls_move_tree():
    store = FakeSyncStorage()
    store.add_yml(_act_path())
    engine = SyncEngine(store, _config())
    yml = HelaoYml(_act_path())
    job = SyncJob(yml=yml, progress=Progress.from_dict({}), priority=0)
    asyncio.run(engine.sync_one(job))
    assert len(store.moved) == 1
    src, dst = store.moved[0]
    assert "RUNS_FINISHED" in str(src)
    assert "RUNS_SYNCED" in str(dst)


def test_sync_one_act_does_not_zip():
    store = FakeSyncStorage()
    store.add_yml(_act_path())
    engine = SyncEngine(store, _config())
    yml = HelaoYml(_act_path())
    job = SyncJob(yml=yml, progress=Progress.from_dict({}), priority=0)
    asyncio.run(engine.sync_one(job))
    assert store.zipped == []


def test_sync_one_seq_calls_zip():
    store = FakeSyncStorage()
    store.add_yml(_seq_path())
    engine = SyncEngine(store, _config())
    yml = HelaoYml(_seq_path())
    job = SyncJob(yml=yml, progress=Progress.from_dict({}), priority=2)
    asyncio.run(engine.sync_one(job))
    assert len(store.zipped) == 1


def test_sync_one_no_upload_when_use_s3_false():
    store = FakeSyncStorage()
    store.add_yml(_act_path())
    engine = SyncEngine(store, _config())
    yml = HelaoYml(_act_path())
    job = SyncJob(yml=yml, progress=Progress.from_dict({}), priority=0)
    asyncio.run(engine.sync_one(job))
    assert store.uploaded_files == []
    assert store.uploaded_bytes == []


def test_sync_one_writes_prg():
    store = FakeSyncStorage()
    store.add_yml(_act_path())
    engine = SyncEngine(store, _config())
    yml = HelaoYml(_act_path())
    job = SyncJob(yml=yml, progress=Progress.from_dict({}), priority=0)
    asyncio.run(engine.sync_one(job))
    assert yml.prg_path in store._prgs


def test_sync_one_concurrent_acts_do_not_block_each_other():
    """Two acts in the same seq can sync simultaneously (both hold read lock)."""
    store = FakeSyncStorage()
    act1 = _FINISHED / "seq1" / "exp1" / "act1" / "20240101T120000_u1-act.yml"
    act2 = _FINISHED / "seq1" / "exp1" / "act2" / "20240101T120001_u2-act.yml"
    store.add_yml(act1)
    store.add_yml(act2)
    engine = SyncEngine(store, _config())

    order = []

    async def run():
        async def sync_act(path):
            yml = HelaoYml(path)
            job = SyncJob(yml=yml, progress=Progress.from_dict({}), priority=0)
            order.append(f"start:{path.parent.name}")
            await engine.sync_one(job)
            order.append(f"done:{path.parent.name}")

        await asyncio.gather(sync_act(act1), sync_act(act2))

    asyncio.run(run())
    # Both started before either finished (concurrent execution)
    assert order.index("start:act1") < order.index("done:act2")
    assert order.index("start:act2") < order.index("done:act1")
    assert len(store.moved) == 2


# ── get_progress ──────────────────────────────────────────────────────────────

def test_get_progress_returns_progress():
    store = FakeSyncStorage()
    act_path = _act_path()
    prg_path = HelaoYml(act_path).prg_path
    store._prgs[prg_path] = {"s3": True, "api": False, "yml": str(act_path)}
    engine = SyncEngine(store, _config())
    p = engine.get_progress(act_path)
    assert p.s3_done is True


def test_get_progress_caches_on_second_call():
    store = FakeSyncStorage()
    act_path = _act_path()
    prg_path = HelaoYml(act_path).prg_path
    store._prgs[prg_path] = {"s3": False, "api": False}
    engine = SyncEngine(store, _config())
    p1 = engine.get_progress(act_path)
    p2 = engine.get_progress(act_path)
    assert p1 is p2


# ── reset_sync ────────────────────────────────────────────────────────────────

def test_reset_sync_moves_synced_to_finished():
    store = FakeSyncStorage()
    synced_dir = _SYNCED / "seq1" / "exp1" / "act1"
    store.add_yml(synced_dir / "20240101T120000_uuid-act.yml")
    engine = SyncEngine(store, _config())
    result = engine.reset_sync(synced_dir)
    assert result is True
    assert len(store.moved) == 1
    src, dst = store.moved[0]
    assert "RUNS_SYNCED" in str(src)
    assert "RUNS_FINISHED" in str(dst)


def test_reset_sync_calls_list_files_for_prg():
    store = FakeSyncStorage()
    synced_dir = _SYNCED / "seq1" / "exp1" / "act1"
    yml_path = synced_dir / "20240101T120000_uuid-act.yml"
    store.add_yml(yml_path)
    prg_path = HelaoYml(yml_path).prg_path
    store._prgs[prg_path] = {"s3": False, "api": False}
    engine = SyncEngine(store, _config())
    # list_files is called but returns empty in FakeSyncStorage (not implemented)
    # so prg removal doesn't happen, but reset_sync still succeeds
    result = engine.reset_sync(synced_dir)
    assert result is True
    # move_tree was called (prg files moved but not removed in fake)
    assert len(store.moved) == 1


def test_reset_sync_handles_exception_returns_false():
    store = FakeSyncStorage()
    store.will_fail = True  # Make move_tree raise exception
    synced_dir = _SYNCED / "seq1" / "exp1" / "act1"
    engine = SyncEngine(store, _config())
    result = engine.reset_sync(synced_dir)
    assert result is False


def test_unsync_dir_reverts_all_ymls():
    store = FakeSyncStorage()
    sync_dir = _SYNCED / "seq1" / "exp1"
    store.add_yml(sync_dir / "act1" / "20240101T120000_u1-act.yml")
    store.add_yml(sync_dir / "act2" / "20240101T120001_u2-act.yml")
    engine = SyncEngine(store, _config())
    engine.unsync_dir(sync_dir)
    # unsync_dir calls reset_sync for each parent dir
    assert len(store.moved) == 2


def test_cleanup_root_removes_empty_dirs():
    store = FakeSyncStorage()
    root = _SYNCED / "seq1"
    store.add_yml(root / "exp1" / "20240101T120000_uuid-exp.yml")
    engine = SyncEngine(store, _config())
    engine.cleanup_root(root)
    # cleanup_root sorts by depth (reverse) and tries to remove empty dirs
    assert len(store.removed_dirs) >= 1


def test_sync_one_with_s3_enabled_uploads():
    store = FakeSyncStorage()
    store.add_yml(_act_path())
    config = _config()
    config["use_s3"] = True
    engine = SyncEngine(store, config)
    yml = HelaoYml(_act_path())
    job = SyncJob(yml=yml, progress=Progress.from_dict({}), priority=0)
    asyncio.run(engine.sync_one(job))
    assert len(store.uploaded_bytes) == 1


def test_sync_one_updates_s3_done_flag():
    store = FakeSyncStorage()
    store.add_yml(_act_path())
    config = _config()
    config["use_s3"] = True
    engine = SyncEngine(store, config)
    yml = HelaoYml(_act_path())
    job = SyncJob(yml=yml, progress=Progress.from_dict({"s3": False}), priority=0)
    result_job = asyncio.run(engine.sync_one(job))
    assert result_job.progress.s3_done is True


def test_update_process_returns_same_job():
    store = FakeSyncStorage()
    store.add_yml(_act_path())
    engine = SyncEngine(store, _config())
    yml = HelaoYml(_act_path())
    job = SyncJob(yml=yml, progress=Progress.from_dict({}), priority=0)
    result_job = asyncio.run(engine.update_process(job))
    assert result_job is job


def test_list_pending_exps_omits_manual():
    store = FakeSyncStorage()
    manual = _FINISHED / "manual_orch_seq_20240101" / "20240101T120000_uuid-exp.yml"
    store.add_yml(manual)
    store.add_yml(_exp_path())
    engine = SyncEngine(store, _config())
    assert len(engine.list_pending_exps(omit_manual=True)) == 1
    assert len(engine.list_pending_exps(omit_manual=False)) == 2


def test_list_pending_acts_omits_manual():
    store = FakeSyncStorage()
    manual = _FINISHED / "manual_orch_seq_20240101" / "20240101T120000_uuid-act.yml"
    store.add_yml(manual)
    store.add_yml(_act_path())
    engine = SyncEngine(store, _config())
    assert len(engine.list_pending_acts(omit_manual=True)) == 1
    assert len(engine.list_pending_acts(omit_manual=False)) == 2


def test_seq_key_without_runs_prefix_returns_full_path():
    """When no RUNS_ prefix found, _seq_key returns full path."""
    store = FakeSyncStorage()
    engine = SyncEngine(store, _config())
    # Path without RUNS_ prefix
    # Manually create a path without RUNS_ prefix
    weird_path = Path("/some/other/path/file.yml")
    # Create a mock yml object
    class MockYml:
        path = weird_path
    mock_yml = MockYml()
    seq_key = engine._seq_key(mock_yml)
    assert seq_key == str(weird_path)
