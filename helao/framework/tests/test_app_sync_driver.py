"""End-to-end tests for the SP6 async data-sync app layer.

Exercises :class:`helao.framework.app.sync_driver.SyncDriver` with two in-memory
fakes (defined inline here, mirroring the ``test_app_orch_api`` convention of
plain ``def test_*`` + ``asyncio.run``):

* ``FakeSyncStorage`` -- a dict-backed yml/prg store with a configurable child
  tree + per-node status, and a call log for ``move_to_synced``/``zip_dir``.
* ``FakeCloudSink`` -- records every upload/register call and returns ``True``.

Coverage:
- ``sync_yml`` PROCEED happy path (act/exp/seq): uploads + move + prg s3/api done;
  seq triggers ``zip_dir``, act/exp do not.
- SOFT_BLOCK when the node itself is active -> no uploads/moves.
- SKIP when already synced / when the yml does not exist.
- REQUEUE_CHILDREN: finished child + self re-enqueued at child-rank / parent-rank.
- active child -> SOFT_BLOCK (no requeue) parity behavior.
- ``get_progress`` creates + persists a Progress when the prg is missing; reads
  the existing prg otherwise.
- lock concurrency: two action syncs under one sequence hold read locks
  concurrently while the sequence sync takes the write lock.
- WIRING OBLIGATION 1: ``move_to_synced`` raising ``PermissionError`` once then
  succeeding -> ``sync_yml`` retries and completes (asyncio.sleep monkeypatched).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import helao.framework.app.sync_driver as sd_mod
from helao.framework.app.sync_driver import SyncDriver

RUN = "RUNS_FINISHED"


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #


class FakeCloudSink:
    """Records upload/register calls; every leg succeeds."""

    def __init__(self) -> None:
        self.upload_bytes_calls: list[tuple[str, bool]] = []
        self.upload_file_calls: list[tuple[str, str]] = []
        self.register_calls: list[tuple[str, str]] = []

    async def upload_bytes(self, data, key, content_type="application/json", compress=False):
        self.upload_bytes_calls.append((key, compress))
        return True

    async def upload_file(self, local_path, key):
        self.upload_file_calls.append((str(local_path), key))
        return True

    def key_exists(self, key):
        return False

    async def register_api(self, req_model, meta_type, retries=5):
        self.register_calls.append((meta_type, req_model.get("technique_name", "")))
        return True


class FakeSyncStorage:
    """Dict-backed yml/prg store with a configurable child tree + call log."""

    def __init__(self) -> None:
        self.ymls: dict[str, dict] = {}
        self.prgs: dict[str, dict] = {}
        self.children: dict[str, list[str]] = {}  # parent_dir -> [child yml path]
        self.hlo: dict[str, list[str]] = {}
        self.misc: dict[str, list[str]] = {}
        self.locks: dict[str, list[str]] = {}
        self.sizes: dict[str, int] = {}
        # call logs
        self.moved: list[str] = []
        self.zipped: list[str] = []
        self.reverted: list[str] = []
        self.cleaned: list[str] = []
        self.removed: list[str] = []
        # move retry control: number of PermissionErrors to raise per path
        self.move_fail_counts: dict[str, int] = {}

    # --- inspection ---
    def exists(self, path):
        return str(path) in self.ymls

    def list_pending(self, finished_root, kind, omit_manual):
        return []

    def list_children(self, parent_dir):
        return [Path(p) for p in self.children.get(str(parent_dir), [])]

    def hlo_files(self, dir_):
        return [Path(p) for p in self.hlo.get(str(dir_), [])]

    def misc_files(self, dir_, node_type):
        return [Path(p) for p in self.misc.get(str(dir_), [])]

    def lock_files(self, dir_):
        return [Path(p) for p in self.locks.get(str(dir_), [])]

    def file_size(self, path):
        return self.sizes.get(str(path), 0)

    # --- yml + prg ---
    def read_yml(self, path):
        return dict(self.ymls.get(str(path), {}))

    def write_yml(self, path, data):
        self.ymls[str(path)] = dict(data)

    def read_prg(self, path):
        return dict(self.prgs.get(str(path), {}))

    def write_prg(self, path, data):
        self.prgs[str(path)] = dict(data)

    def remove_prg(self, path):
        self.prgs.pop(str(path), None)

    # --- mutation ---
    def move_to_synced(self, path):
        sp = str(path)
        n = self.move_fail_counts.get(sp, 0)
        if n > 0:
            self.move_fail_counts[sp] = n - 1
            raise PermissionError(f"{sp} in use")
        self.moved.append(sp)
        target = sp.replace("RUNS_FINISHED", "RUNS_SYNCED")
        # migrate the yml entry so downstream prg writes line up
        if sp in self.ymls:
            self.ymls[target] = self.ymls.pop(sp)
        return Path(target)

    def revert_to_finished(self, path):
        self.reverted.append(str(path))
        return Path(str(path).replace("RUNS_SYNCED", "RUNS_FINISHED"))

    def move_tree(self, src, dst):
        return Path(dst)

    def zip_dir(self, path):
        self.zipped.append(str(path))
        return Path(f"{path}.zip")

    def cleanup_empty(self, path):
        self.cleaned.append(str(path))
        return True

    def remove(self, path):
        self.removed.append(str(path))


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _seq_dir():
    return f"/root/{RUN}/wk/dt/240101.000000000000_seq"


def _exp_dir():
    return f"{_seq_dir()}/240101.000001000000_exp"


def _act_dir():
    return f"{_exp_dir()}/240101.000002000000_act"


def _seq_yml():
    return f"{_seq_dir()}/240101.000000000000-seq.yml"


def _exp_yml():
    return f"{_exp_dir()}/240101.000001000000-exp.yml"


def _act_yml():
    return f"{_act_dir()}/240101.000002000000-act.yml"


def _driver(storage, cloud, **kw):
    return SyncDriver(storage, cloud, {"aws_bucket": "b"}, max_tasks=2, **kw)


def _seed_finished_act(storage, *, uuid="act-uuid-1"):
    storage.ymls[_act_yml()] = {
        "yml": _act_yml(),
        "action_uuid": uuid,
        "action_name": "do",
        "technique_name": "tn",
    }


# --------------------------------------------------------------------------- #
# PROCEED happy paths
# --------------------------------------------------------------------------- #


def test_sync_yml_action_proceed_uploads_and_moves():
    storage, cloud = FakeSyncStorage(), FakeCloudSink()
    _seed_finished_act(storage)
    drv = _driver(storage, cloud)

    result = asyncio.run(drv.sync_yml(Path(_act_yml())))

    # uploaded the action doc + registered API
    assert any(k.startswith("action/") for k, _ in cloud.upload_bytes_calls)
    assert ("action", "tn") in cloud.register_calls
    # moved to synced; no zip for an action
    assert _act_yml() in storage.moved
    assert storage.zipped == []
    # shipped progress dict reports both legs done (process_metas stripped)
    assert isinstance(result, dict)
    assert result["s3"] is True and result["api"] is True
    assert "process_metas" not in result


def test_sync_yml_action_uploads_hlo_and_misc_files():
    storage, cloud = FakeSyncStorage(), FakeCloudSink()
    _seed_finished_act(storage)
    storage.hlo[_act_dir()] = [f"{_act_dir()}/data.hlo"]
    storage.misc[_act_dir()] = [f"{_act_dir()}/aux.txt"]
    storage.sizes[f"{_act_dir()}/data.hlo"] = 10  # small -> json
    drv = _driver(storage, cloud)

    # patch hlo_loader.read_hlo so we don't touch disk
    orig = sd_mod.hlo_loader.read_hlo
    sd_mod.hlo_loader.read_hlo = lambda p, *a, **k: ({"m": 1}, {"d": [1, 2]})
    try:
        asyncio.run(drv.sync_yml(Path(_act_yml())))
    finally:
        sd_mod.hlo_loader.read_hlo = orig

    # hlo -> upload_bytes (json), misc -> upload_file
    assert any("data.hlo.json" in k for k, _ in cloud.upload_bytes_calls)
    assert any("aux.txt" in k for _, k in cloud.upload_file_calls)


def test_sync_yml_sequence_proceed_triggers_zip():
    storage, cloud = FakeSyncStorage(), FakeCloudSink()
    storage.ymls[_seq_yml()] = {"yml": _seq_yml(), "sequence_uuid": "s1"}
    # no children -> children all synced (empty), proceed
    drv = _driver(storage, cloud)

    asyncio.run(drv.sync_yml(Path(_seq_yml())))

    assert _seq_yml() in storage.moved
    assert len(storage.zipped) == 1  # sequence zips its synced dir


def test_sync_yml_experiment_proceed_no_zip():
    storage, cloud = FakeSyncStorage(), FakeCloudSink()
    storage.ymls[_exp_yml()] = {"yml": _exp_yml(), "experiment_uuid": "e1"}
    drv = _driver(storage, cloud)

    asyncio.run(drv.sync_yml(Path(_exp_yml())))

    assert _exp_yml() in storage.moved
    assert storage.zipped == []


# --------------------------------------------------------------------------- #
# SOFT_BLOCK / SKIP
# --------------------------------------------------------------------------- #


def test_sync_yml_soft_block_when_node_active():
    storage, cloud = FakeSyncStorage(), FakeCloudSink()
    active_yml = _act_yml().replace("RUNS_FINISHED", "RUNS_ACTIVE")
    storage.ymls[active_yml] = {"yml": active_yml, "action_uuid": "a"}
    drv = _driver(storage, cloud)

    result = asyncio.run(drv.sync_yml(Path(active_yml)))

    assert result is False
    assert cloud.upload_bytes_calls == []
    assert storage.moved == []


def test_sync_yml_skip_when_not_exists():
    storage, cloud = FakeSyncStorage(), FakeCloudSink()
    drv = _driver(storage, cloud)

    result = asyncio.run(drv.sync_yml(Path(_act_yml())))

    assert result is True
    assert cloud.upload_bytes_calls == []
    assert storage.moved == []


def test_sync_yml_skip_when_already_synced():
    storage, cloud = FakeSyncStorage(), FakeCloudSink()
    _seed_finished_act(storage)
    prg_path = str(Path(_act_yml()).with_suffix(".prg"))
    storage.prgs[prg_path] = {"yml": _act_yml(), "s3": True, "api": True,
                              "files_pending": [], "files_s3": {}}
    drv = _driver(storage, cloud)

    result = asyncio.run(drv.sync_yml(Path(_act_yml())))

    assert result is True
    assert cloud.upload_bytes_calls == []
    assert storage.moved == []


# --------------------------------------------------------------------------- #
# REQUEUE_CHILDREN / active-child parity
# --------------------------------------------------------------------------- #


def _finished_child_dir():
    """The experiment's FINISHED-tree child parent dir (where the exp yml lives)."""
    return _exp_dir()


def _active_child_dir():
    """The experiment's ACTIVE-tree child parent dir (sibling status tree)."""
    return _exp_dir().replace("RUNS_FINISHED", "RUNS_ACTIVE")


def test_sync_yml_requeue_children_when_child_finished():
    storage, cloud = FakeSyncStorage(), FakeCloudSink()
    storage.ymls[_exp_yml()] = {"yml": _exp_yml(), "experiment_uuid": "e1"}
    # one finished (not synced) child action, registered under the FINISHED-tree
    # child parent dir so the driver tags it "finished".
    storage.ymls[_act_yml()] = {"yml": _act_yml(), "action_uuid": "a"}
    storage.children[_finished_child_dir()] = [_act_yml()]
    drv = _driver(storage, cloud)

    result = asyncio.run(drv.sync_yml(Path(_exp_yml()), rank=5))

    assert result is False
    # nothing uploaded/moved; instead children+self queued
    assert storage.moved == []
    queued = []
    while not drv.task_queue.empty():
        queued.append(drv.task_queue.get_nowait())
    ranks = {Path(p).name: r for r, p in queued}
    # child re-queued at rank-2 (==3), self at rank-1 (==4)
    assert ranks[Path(_act_yml()).name] == 3
    assert ranks[Path(_exp_yml()).name] == 4


def test_sync_yml_active_child_soft_blocks_no_requeue():
    storage, cloud = FakeSyncStorage(), FakeCloudSink()
    storage.ymls[_exp_yml()] = {"yml": _exp_yml(), "experiment_uuid": "e1"}
    # one ACTIVE child, registered under the experiment's ACTIVE-tree child
    # parent dir as a normal *-act.yml. No finished/synced children. The driver
    # tags it "active" by which tree it came from -> decide_sync SOFT_BLOCKs.
    active_child = f"{_active_child_dir()}/240101.000002000000-act.yml"
    storage.children[_active_child_dir()] = [active_child]
    drv = _driver(storage, cloud)

    result = asyncio.run(drv.sync_yml(Path(_exp_yml()), rank=5))

    assert result is False
    assert storage.moved == []
    assert drv.task_queue.empty()  # active child => bare soft-block, no requeue


# --------------------------------------------------------------------------- #
# get_progress
# --------------------------------------------------------------------------- #


def test_get_progress_creates_and_persists_when_missing():
    storage, cloud = FakeSyncStorage(), FakeCloudSink()
    _seed_finished_act(storage)
    drv = _driver(storage, cloud)

    prog = drv.get_progress(Path(_act_yml()))

    assert prog.s3_done is False and prog.api_done is False
    # action default schema fields present + persisted
    d = prog.to_dict()
    assert "files_pending" in d and "files_s3" in d
    prg_path = str(Path(_act_yml()).with_suffix(".prg"))
    assert prg_path in storage.prgs


def test_get_progress_reads_existing():
    storage, cloud = FakeSyncStorage(), FakeCloudSink()
    _seed_finished_act(storage)
    prg_path = str(Path(_act_yml()).with_suffix(".prg"))
    storage.prgs[prg_path] = {"yml": _act_yml(), "s3": True, "api": False,
                              "files_pending": ["x"], "files_s3": {}}
    drv = _driver(storage, cloud)

    prog = drv.get_progress(Path(_act_yml()))

    assert prog.s3_done is True and prog.api_done is False
    assert prog.to_dict()["files_pending"] == ["x"]


# --------------------------------------------------------------------------- #
# lock concurrency
# --------------------------------------------------------------------------- #


def test_two_action_read_locks_held_concurrently():
    storage, cloud = FakeSyncStorage(), FakeCloudSink()
    drv = _driver(storage, cloud)

    from contextlib import AsyncExitStack

    async def scenario():
        s1, s2 = AsyncExitStack(), AsyncExitStack()
        await drv._acquire_hierarchy_locks(s1, Path(_act_yml()))
        # A second action in a DIFFERENT experiment under the SAME sequence: it
        # shares the sequence read-lock (reader) but holds a distinct experiment
        # mutex, so it does NOT block on the first action's exp lock. (Two actions
        # in the *same* experiment would deadlock on the shared exp mutex by
        # design -- legacy serializes same-experiment actions.)
        act2 = (
            f"{_seq_dir()}/240101.000005000000_exp/240101.000006000000_act"
            f"/240101.000006000000-act.yml"
        )
        await drv._acquire_hierarchy_locks(s2, Path(act2))
        seq_key, _ = __import__(
            "helao.framework.domain.sync.paths", fromlist=["node_keys"]
        ).node_keys(Path(_act_yml()))
        readers = drv.seq_locks[seq_key]._readers
        await s1.aclose()
        await s2.aclose()
        return readers

    readers = asyncio.run(scenario())
    assert readers == 2  # both actions held the sequence read lock at once


def test_sequence_takes_write_lock():
    storage, cloud = FakeSyncStorage(), FakeCloudSink()
    drv = _driver(storage, cloud)

    from contextlib import AsyncExitStack

    async def scenario():
        stack = AsyncExitStack()
        await drv._acquire_hierarchy_locks(stack, Path(_seq_yml()))
        seq_key, _ = __import__(
            "helao.framework.domain.sync.paths", fromlist=["node_keys"]
        ).node_keys(Path(_seq_yml()))
        is_writer = drv.seq_locks[seq_key]._writer
        await stack.aclose()
        return is_writer

    assert asyncio.run(scenario()) is True


# --------------------------------------------------------------------------- #
# WIRING OBLIGATION 1: PermissionError retry
# --------------------------------------------------------------------------- #


def test_move_to_synced_retries_past_permission_error():
    storage, cloud = FakeSyncStorage(), FakeCloudSink()
    _seed_finished_act(storage)
    # the yml move raises PermissionError once, then succeeds
    storage.move_fail_counts[_act_yml()] = 1
    drv = _driver(storage, cloud)

    slept = []

    async def fake_sleep(d):
        slept.append(d)

    orig_sleep = sd_mod.asyncio.sleep
    sd_mod.asyncio.sleep = fake_sleep
    try:
        result = asyncio.run(drv.sync_yml(Path(_act_yml())))
    finally:
        sd_mod.asyncio.sleep = orig_sleep

    assert isinstance(result, dict)
    assert _act_yml() in storage.moved  # eventually moved
    assert slept  # the retry loop slept at least once between attempts
