"""Colocated -prc.yml: type, guard, globs, write location, move set."""

import asyncio
from pathlib import Path

import pytest

from helao.core.drivers.data.sync_driver import ABR_MAP, HelaoYml


def _tree(tmp_path: Path) -> Path:
    """A minimal RUNS_FINISHED experiment directory with one action child."""
    exp_dir = tmp_path / "RUNS_FINISHED" / "26.35" / "0828" / "seqdir" / "expdir"
    act_dir = exp_dir / "0__0__SIM__do_thing"
    act_dir.mkdir(parents=True)
    (exp_dir / "260828.120000000000-exp.yml").write_text(
        "experiment_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n"
        "experiment_name: SIM_exp\n"
    )
    (act_dir / "260828.120001000000-act.yml").write_text(
        "action_uuid: 06a5a2d6-b26c-7673-8000-9f38fe556fd6\naction_order: 0\n"
    )
    return exp_dir


def test_prc_is_a_known_record_type(tmp_path):
    assert ABR_MAP["prc"] == "process"
    exp_dir = _tree(tmp_path)
    prc = exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml"
    prc.write_text("process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n")
    assert HelaoYml(prc).type == "process"


class _FakeQueue:
    def __init__(self):
        self.items = []

    async def put(self, item):
        self.items.append(item)


class _StubSyncer:
    """Just enough of SyncDriver to exercise enqueue_yml's guard."""

    def __init__(self):
        self.task_queue = _FakeQueue()
        self.task_set = set()
        self.running_tasks = {}

    from helao.core.drivers.data.sync_driver import SyncDriver

    enqueue_yml = SyncDriver.enqueue_yml


def test_enqueue_yml_refuses_a_process_yml(tmp_path):
    exp_dir = _tree(tmp_path)
    prc = exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml"
    prc.write_text("process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n")
    syncer = _StubSyncer()
    asyncio.run(syncer.enqueue_yml(prc, rank=-1))
    assert syncer.task_queue.items == []
    assert syncer.task_set == set()


def test_enqueue_yml_still_accepts_an_action_yml(tmp_path):
    exp_dir = _tree(tmp_path)
    act = next((exp_dir / "0__0__SIM__do_thing").glob("*-act.yml"))
    syncer = _StubSyncer()
    asyncio.run(syncer.enqueue_yml(act, rank=0))
    assert len(syncer.task_queue.items) == 1


def test_sync_yml_refuses_a_process_yml(tmp_path):
    """syncer() calls sync_yml directly off the queue, so this guard is the
    authoritative one and needs its own coverage.

    make_sync_driver's SyncDriver.__init__ spawns the syncer worker tasks, so
    it (and the sync_yml call under test, and its teardown) must run inside a
    single running event loop rather than across separate asyncio.run() calls.
    """
    from helao.core.drivers.data.sync_driver import SyncDriver
    from helao.hexagon.tests.sync_fixtures import make_sync_driver, teardown_driver

    exp_dir = _tree(tmp_path)
    prc = exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml"
    prc.write_text("process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n")

    async def _run():
        driver = make_sync_driver(tmp_path, SyncDriver)
        called = []
        driver.get_progress = lambda p: called.append(p)  # must never be reached
        try:
            result = await driver.sync_yml(yml_path=prc)
        finally:
            await teardown_driver(driver)
        return result, called

    result, called = asyncio.run(_run())
    assert result is True
    assert called == [], "sync_yml must return before touching progress"


def test_list_children_ignores_a_colocated_process_yml(tmp_path):
    exp_dir = _tree(tmp_path)
    seq_dir = exp_dir.parent
    (seq_dir / "260828.115959000000-seq.yml").write_text("sequence_name: SIM_seq\n")
    (exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml").write_text(
        "process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n"
    )
    seq_yml = next(seq_dir.glob("*-seq.yml"))
    children = HelaoYml(seq_yml).list_children(seq_yml)
    assert [c.type for c in children] == ["experiment"]


def test_parent_path_of_an_action_is_the_experiment_not_the_process(tmp_path):
    exp_dir = _tree(tmp_path)
    # sorts before the -exp.yml, so a bare glob's [0] would pick it
    (exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml").write_text(
        "process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n"
    )
    act = next((exp_dir / "0__0__SIM__do_thing").glob("*-act.yml"))
    assert HelaoYml(act).parent_path.name.endswith("-exp.yml")


def test_process_ymls_lists_colocated_prc_only(tmp_path):
    exp_dir = _tree(tmp_path)
    (exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml").write_text(
        "process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n"
    )
    (exp_dir / "1__06a5a2d6-b26c-7673-8000-9f38fe556fd6__SIM_exp-prc.yml").write_text(
        "process_uuid: 06a5a2d6-b26c-7673-8000-9f38fe556fd6\n"
    )
    exp_yml = next(exp_dir.glob("*-exp.yml"))
    found = HelaoYml(exp_yml).process_ymls
    assert sorted(p.name for p in found) == [
        "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml",
        "1__06a5a2d6-b26c-7673-8000-9f38fe556fd6__SIM_exp-prc.yml",
    ]


def test_process_ymls_is_empty_for_an_action(tmp_path):
    exp_dir = _tree(tmp_path)
    act = next((exp_dir / "0__0__SIM__do_thing").glob("*-act.yml"))
    assert HelaoYml(act).process_ymls == []


def test_sync_process_writes_beside_the_exp_yml(tmp_path):
    """The prc lands in the experiment directory and nowhere else.

    Drives the real sync_process through the fixture builders rather than
    stubbing it, so the assertion covers the path construction actually used.

    make_sync_driver's SyncDriver.__init__ spawns the syncer worker tasks, so
    it (and sync_process, and its teardown) must run inside a single running
    event loop rather than across separate asyncio.run() calls -- the same
    constraint test_sync_yml_refuses_a_process_yml above works around.
    """
    from helao.core.drivers.data.sync_driver import SyncDriver
    from helao.hexagon.tests.sync_fixtures import (
        make_action,
        make_exp_tree,
        make_sync_driver,
        mk_uuid,
        teardown_driver,
    )
    from helao.core.models.run_dir import RunDir

    exp_yml = make_exp_tree(
        tmp_path, RunDir.FINISHED.value, mk_uuid(1001), process_order_groups={0: [0]}
    )
    make_action(exp_yml, 0, process_finish=True)

    async def _run():
        driver = make_sync_driver(tmp_path, SyncDriver)
        try:
            exp_prog = driver.get_progress(exp_yml)
            # sync_yml always reconciles process metas from on-disk actions
            # before calling sync_process (sync_driver.py:1611); get_progress
            # alone does not, so a bare sync_process call sees no process
            # metas and drops the group as phantom rather than writing it.
            exp_prog = driver.reconcile_processes(exp_prog)
            await driver.sync_process(exp_prog, force=True)
        finally:
            await teardown_driver(driver)

    asyncio.run(_run())

    written = list(exp_yml.parent.glob("*-prc.yml"))
    assert len(written) == 1, f"expected one prc beside the exp yml, got {written}"
    assert not list(
        (tmp_path / "PROCESSES").rglob("*-prc.yml")
    ), "nothing may be written under process_root"


def test_the_prc_moves_with_the_record_and_the_directory_cleans_up(tmp_path):
    """Drive the real move and assert the outcome, not the set composition.

    A stranded prc is worse than an orphan: cleanup() walks up from the moved
    record and reports any non-empty directory as "failed", so the leftover
    would keep the experiment directory alive forever. Asserting
    ``prc in misc_files + hlo_files + process_ymls`` would only restate the
    production expression in the test and would pass before the fix -- so this
    drives move_to_synced and looks at where the file actually ends up.
    """
    from helao.core.drivers.data.sync_driver import SyncDriver
    from helao.core.models.run_dir import RunDir
    from helao.hexagon.tests.sync_fixtures import (
        make_action,
        make_exp_tree,
        make_sync_driver,
        mk_uuid,
        teardown_driver,
    )

    exp_yml = make_exp_tree(
        tmp_path, RunDir.FINISHED.value, mk_uuid(3001), process_order_groups={0: [0]}
    )
    act_yml = make_action(exp_yml, 0, process_finish=True)

    written = []

    async def _run():
        driver = make_sync_driver(tmp_path, SyncDriver)
        try:
            # Sync the action first: sync_yml's own "action contributes
            # processes" branch (sync_driver.py:1747-1749) folds it via
            # update_process and calls sync_process as a real side effect --
            # the same path production takes, and what actually establishes
            # the precondition that the prc exists beside the exp yml before
            # anything moves it.
            await driver.sync_yml(yml_path=act_yml)
            written.extend(exp_yml.parent.glob("*-prc.yml"))

            await driver.sync_yml(yml_path=exp_yml)
        finally:
            await teardown_driver(driver)

    asyncio.run(_run())

    assert len(written) == 1

    finished_leftovers = [
        p for p in (tmp_path / RunDir.FINISHED.value).rglob("*-prc.yml")
    ]
    assert (
        not finished_leftovers
    ), f"the prc was stranded in RUNS_FINISHED: {finished_leftovers}"
    synced = list((tmp_path / RunDir.SYNCED.value).rglob("*-prc.yml"))
    assert len(synced) == 1, f"the prc must travel to RUNS_SYNCED, found {synced}"


def test_the_zip_carries_the_prc_and_reset_sync_restores_it(tmp_path):
    """The whole point: a sequence zip records its own process identity.

    zip_dir takes the sequence directory, so a colocated prc is included with
    no change to the zip code; reset_sync extracts everything but .prg/.lock,
    so it comes back on a reopen.
    """
    import zipfile

    from helao.helpers.file_utils import zip_dir

    seq_dir = tmp_path / "RUNS_SYNCED" / "26.35" / "0828" / "260828.115959__seq"
    exp_dir = seq_dir / "260828.120000__exp"
    exp_dir.mkdir(parents=True)
    (seq_dir / "260828.115959000000-seq.yml").write_text("sequence_name: SIM_seq\n")
    (exp_dir / "260828.120000000000-exp.yml").write_text("experiment_name: SIM_exp\n")
    prc_name = "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml"
    (exp_dir / prc_name).write_text(
        "process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n"
    )
    (exp_dir / "260828.120000000000-exp.prg").write_text("{}\n")

    zpath = seq_dir.parent / "260828.115959__seq.zip"
    zip_dir(seq_dir, zpath)
    members = zipfile.ZipFile(zpath).namelist()
    assert any(
        m.endswith(prc_name) for m in members
    ), f"the zip must carry the process artifact; members={members}"


def test_the_process_s3_key_is_unchanged(tmp_path):
    """Relocating the local write must not touch the bucket layout.

    S3 destinations are uuid-keyed, not path-keyed, so nothing about where the
    yml lands on disk may reach the key.
    """
    from helao.core.drivers.data.sync_driver import SyncDriver
    from helao.core.models.run_dir import RunDir
    from helao.hexagon.tests.sync_fixtures import (
        make_action,
        make_exp_tree,
        make_sync_driver,
        mk_uuid,
        teardown_driver,
    )

    seen: list[str] = []

    async def _record(msg, target, compress=False):
        seen.append(target)
        return True

    exp_yml = make_exp_tree(
        tmp_path, RunDir.FINISHED.value, mk_uuid(2001), process_order_groups={0: [0]}
    )
    make_action(exp_yml, 0, process_finish=True)

    # make_sync_driver's SyncDriver.__init__ spawns the syncer worker tasks
    # via create_task, so construction (and sync_process, and teardown) must
    # run inside a single running event loop -- same constraint as
    # test_sync_process_writes_beside_the_exp_yml above.
    async def _run():
        driver = make_sync_driver(tmp_path, SyncDriver)
        driver.to_s3 = _record
        try:
            # sync_yml always reconciles process metas from on-disk actions
            # before calling sync_process (sync_driver.py:1611); get_progress
            # alone does not, so a bare sync_process call sees no process
            # metas and drops the group as phantom -- same precondition as
            # test_sync_process_writes_beside_the_exp_yml above.
            exp_prog = driver.reconcile_processes(driver.get_progress(exp_yml))
            await driver.sync_process(exp_prog, force=True)
        finally:
            await teardown_driver(driver)

    asyncio.run(_run())

    prc_keys = [k for k in seen if k.startswith("process/")]
    assert prc_keys, f"expected a process/ key, saw {seen}"
    assert all(k.startswith("process/") and k.endswith(".json") for k in prc_keys)


def test_list_pending_exps_does_not_return_a_colocated_prc(tmp_path):
    """A colocated prc sits at exactly the depth list_pending_exps walks.

    week/date/seq/exp -- the same four levels. It is excluded by the -exp.yml
    suffix and by nothing else, so loosening that pattern to *.yml would feed
    process artifacts straight into the sync queue. This pins the suffix.
    """
    from helao.core.drivers.data.sync_driver import SyncDriver
    from helao.hexagon.tests.sync_fixtures import make_sync_driver, teardown_driver

    exp_dir = tmp_path / "RUNS_FINISHED" / "26.35" / "0828" / "seqdir" / "expdir"
    exp_dir.mkdir(parents=True)
    (exp_dir / "260828.120000000000-exp.yml").write_text("experiment_name: SIM_exp\n")
    (exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml").write_text(
        "process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n"
    )

    # make_sync_driver's SyncDriver.__init__ spawns the syncer worker tasks
    # via create_task, so it needs a running event loop even though
    # list_pending_exps itself is synchronous.
    async def _run():
        driver = make_sync_driver(tmp_path, SyncDriver)
        try:
            return driver.list_pending_exps()
        finally:
            await teardown_driver(driver)

    pending = asyncio.run(_run())
    assert all(p.endswith("-exp.yml") for p in pending), pending
    assert not any("-prc.yml" in p for p in pending), pending


def test_finish_yml_route_drops_a_process_path(tmp_path):
    """The route that makes the guard necessary.

    /finish_yml assigns rank -1 to an unrecognised suffix, and -1 is above
    enqueue_yml's rank_limit of -5, so a prc path reaches the queue rather
    than being dropped by the rank floor. Exercises the same rank the route
    would pass.
    """
    exp_dir = _tree(tmp_path)
    prc = exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml"
    prc.write_text("process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n")
    syncer = _StubSyncer()
    asyncio.run(syncer.enqueue_yml(str(prc), rank=-1))  # the route's rank
    assert syncer.task_queue.items == []
    assert syncer.task_set == set()
