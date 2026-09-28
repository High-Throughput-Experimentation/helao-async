"""A child that finishes syncing must hand its parent a fresh re-queue budget.

Station report (uvis4_hex, 2026-09-28): a full UVIS_GAIA_preset sequence
finished, but its auto-analysis never dispatched until the group restarted.

A parent whose children are still unsynced re-queues itself one rank lower on
every pass, and enqueue_yml drops anything below rank_limit (-5). A sequence
enters at rank 2, so it gets about eight passes; a sequence whose actions are
still uploading spends them, is dropped silently (the drop logs at DEBUG),
and nothing re-queues it until the startup sweep. The parent is now
re-queued at its entry rank each time one of its children ships.
"""

import asyncio

import pytest

import helao.core.drivers.data.sync_driver as legacy_mod
import helao.hexagon.adapters.native.sync_driver as native_mod
from helao.hexagon.tests.sync_fixtures import (
    make_action,
    make_exp_tree,
    make_sync_driver,
    mk_uuid,
    teardown_driver,
)


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_a_synced_action_requeues_its_experiment(tmp_path, mod):
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1))
        act_yml = make_action(exp_yml, 0)
        calls = []

        async def record(upath, rank=0, rank_limit=-5):
            calls.append((str(upath), rank))

        async def accept(msg=None, target=None, compress=False, retries=5):
            return True

        drv.to_s3 = accept
        drv.enqueue_yml = record
        await asyncio.wait_for(drv.sync_yml(yml_path=act_yml, rank=-4), timeout=15)
        assert (str(exp_yml), 1) in calls, calls
    finally:
        await teardown_driver(drv)
