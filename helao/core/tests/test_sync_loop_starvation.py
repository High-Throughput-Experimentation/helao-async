"""``sync_yml`` must not hold the event loop while it parses records.

Station report (note1_hex, 2026-10-01): after a restart SYNC refused
connections on its own port for ~4.5 minutes. A 296-experiment XRFS
``-seq.yml`` (9.7 MB, ~4 s per parse) re-entered ``sync_yml`` every ~15 s while
its experiments were still uploading, and each pass parsed it and loaded
every child yml on the event loop, so uvicorn never got the loop long enough
to bind.

Two guards, each pinned here against both driver copies:

* a parent whose child is still queued or running is re-queued one rank lower
  without being parsed at all;
* the parse and the child enumeration run in a worker thread, so the loop keeps
  ticking while they do.
"""

import asyncio
import time

import pytest

import helao.core.drivers.data.sync_driver as legacy_mod
import helao.hexagon.adapters.native.sync_driver as native_mod
from helao.hexagon.tests.sync_fixtures import (
    drain,
    make_action,
    make_exp_tree,
    make_sync_driver,
    mk_uuid,
    teardown_driver,
)


async def _ticks_during(coro, interval=0.01):
    """Run ``coro`` and count how often the loop ran a 10 ms ticker meanwhile."""
    ticks = 0
    done = False

    async def ticker():
        nonlocal ticks
        while not done:
            await asyncio.sleep(interval)
            ticks += 1

    t = asyncio.create_task(ticker())
    try:
        result = await coro
    finally:
        done = True
        await t
    return result, ticks


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_parent_with_a_queued_child_is_requeued_unparsed(tmp_path, mod):
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1))
        act_yml = make_action(exp_yml, 0)
        drv.task_set.add(act_yml.name)
        calls = []

        async def record(upath, rank=0, rank_limit=-5):
            calls.append((str(upath), rank))

        def no_parse(*a, **k):
            raise AssertionError("parent parsed while its child is queued")

        drv.enqueue_yml = record
        drv.get_progress = no_parse
        assert await drv.sync_yml(yml_path=exp_yml, rank=1) is False
        assert calls == [(str(exp_yml), 0)]
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_record_parse_runs_off_the_event_loop(tmp_path, mod):
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1))
        act_yml = make_action(exp_yml, 0)

        async def record(upath, rank=0, rank_limit=-5):
            pass

        async def accept(msg=None, target=None, compress=False, retries=5):
            return True

        real = drv.get_progress

        def slow_progress(path):
            time.sleep(0.3)  # a large yml's parse holds the thread, not the loop
            return real(path)

        drv.to_s3 = accept
        drv.enqueue_yml = record
        drv.get_progress = slow_progress
        _, ticks = await _ticks_during(drv.sync_yml(yml_path=act_yml, rank=0))
        assert ticks >= 10, f"event loop ran only {ticks} ticks during the parse"
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_child_enumeration_runs_off_the_event_loop(tmp_path, mod, monkeypatch):
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1))
        make_action(exp_yml, 0)  # finished, unsynced: the parent must wait

        async def record(upath, rank=0, rank_limit=-5):
            pass

        real = mod.HelaoYml.list_children

        def slow_children(self, path):
            time.sleep(0.15)  # 296 child ymls take a while to load
            return real(self, path)

        monkeypatch.setattr(mod.HelaoYml, "list_children", slow_children)
        drv.enqueue_yml = record
        result, ticks = await _ticks_during(drv.sync_yml(yml_path=exp_yml, rank=1))
        assert result is False
        assert ticks >= 10, f"event loop ran only {ticks} ticks during enumeration"
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_a_reposted_shipped_child_does_not_strand_its_parent(tmp_path, mod):
    """Review finding: a shipped child counted as busy dropped its parent."""
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1))
        act_yml = make_action(exp_yml, 3, process_finish=True)
        real_enqueue = drv.enqueue_yml

        async def no_requeue(*a, **k):
            pass

        drv.enqueue_yml = no_requeue
        assert await drv.sync_yml(yml_path=act_yml, rank=0)  # the child ships
        drv.enqueue_yml = real_enqueue
        assert mod._prg_is_complete(act_yml.with_suffix(".prg"))

        # the shipped action is re-posted at its finish_yml rank, beside its parent
        await drv.enqueue_yml(act_yml, 0)
        await drv.enqueue_yml(exp_yml, 0)
        await drain(drv, timeout=30)
        assert mod._prg_is_complete(exp_yml.with_suffix(".prg"))
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_parent_with_a_running_child_is_requeued_unparsed(tmp_path, mod):
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1))
        act_yml = make_action(exp_yml, 0)
        drv.running_tasks[act_yml.name] = None
        calls = []

        async def record(upath, rank=0, rank_limit=-5):
            calls.append((str(upath), rank))

        def no_parse(*a, **k):
            raise AssertionError("parent parsed while its child is running")

        drv.enqueue_yml = record
        drv.get_progress = no_parse
        assert await drv.sync_yml(yml_path=exp_yml, rank=2) is False
        assert calls == [(str(exp_yml), 1)]
    finally:
        drv.running_tasks.clear()
        await teardown_driver(drv)
