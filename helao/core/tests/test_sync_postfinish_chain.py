"""sync_yml runs the configured post-finish chain (spec §6), both drivers."""

import asyncio
import textwrap
from pathlib import Path

import pytest

import helao.core.drivers.data.sync_driver as legacy_mod
import helao.hexagon.adapters.native.sync_driver as native_mod
from helao.core.hooks import HookConfigError
from helao.helpers import dispatcher as dispatcher_mod
from helao.helpers.run_state import DONE
from helao.hexagon.tests.sync_fixtures import (
    make_action,
    make_exp_tree,
    make_sync_driver,
    mk_uuid,
    teardown_driver,
    ts,
    write_yml,
)

MODS = [legacy_mod, native_mod]

FAILING_HOOK = """
from helao.core.hooks import FinishHook
class Hook(FinishHook):
    blocking = {blocking}
    phase = "postfinish"
    async def run(self, ctx):
        raise RuntimeError("push failed")
"""


def _hook_file(tmp_path, name, body) -> str:
    p = tmp_path / f"{name}.py"
    p.write_text(textwrap.dedent(body))
    return str(p)


def _accept(drv):
    async def accept(msg=None, target=None, compress=False, retries=5):
        return True

    drv.to_s3 = accept


def _no_requeue(drv):
    async def record(upath, rank=0, rank_limit=-5):
        return None

    drv.enqueue_yml = record


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_driver_exposes_default_chain_and_no_auto_analyses(tmp_path, mod):
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        assert list(drv.postfinish) == ["action", "experiment", "sequence"]
        assert list(drv.postfinish["sequence"].cfg) == ["s3_upload"]
        assert not hasattr(drv, "auto_analyses")
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_explicit_config_owns_the_chain_and_bad_hook_raises_at_startup(
    tmp_path, mod
):
    with pytest.raises(HookConfigError):
        make_sync_driver(
            tmp_path,
            mod.SyncDriver,
            postfinish_hooks={"action": {"no_such_hook": ["*"]}},
        )
    drv = make_sync_driver(tmp_path, mod.SyncDriver, postfinish_hooks={"action": {}})
    try:
        assert (
            drv.postfinish["action"].cfg == {} and drv.postfinish["sequence"].cfg == {}
        )
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_blocking_failure_after_s3_keeps_record_unsynced_and_retry_resumes(
    tmp_path, mod
):
    failing = _hook_file(tmp_path, "push_api", FAILING_HOOK.format(blocking="True"))
    drv = make_sync_driver(
        tmp_path,
        mod.SyncDriver,
        postfinish_hooks={"action": {"s3_upload": ["*"], failing: ["*"]}},
    )
    try:
        _accept(drv)
        _no_requeue(drv)
        journal = []
        drv._journal = lambda yml_path, state: journal.append((yml_path.name, state))
        act = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        assert await asyncio.wait_for(drv.sync_yml(yml_path=act), timeout=15) is False
        d = mod.Progress(act).dict
        assert d["s3"] is True and d["api"] is True  # s3_upload ran and finished
        assert d["hooks"]["s3_upload"]["state"] == "done"
        assert d["hooks"][failing]["state"] == "failed"
        assert d["synced"] is False
        assert mod.HelaoYml(act).status == "finished"  # not synced despite s3+api
        assert journal == []
        # retry: the hook instance is created once per server, so "fix" it by
        # swapping its run in place, then run the same record again.
        drv.postfinish["action"].hooks[failing].run = _ok_run  # type: ignore[assignment]
        result = await asyncio.wait_for(drv.sync_yml(yml_path=act), timeout=15)
        assert isinstance(result, dict)
        d = mod.Progress(act).dict
        assert d["synced"] is True and d["hooks"][failing]["state"] == "done"
        assert mod.HelaoYml(act).status == "synced"
        assert journal == [(act.name, DONE)]
    finally:
        await teardown_driver(drv)


async def _ok_run(ctx):
    return None


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_non_blocking_failure_still_syncs_journals_and_requeues_parent(
    tmp_path, mod, caplog
):
    failing = _hook_file(tmp_path, "notify", FAILING_HOOK.format(blocking="False"))
    drv = make_sync_driver(
        tmp_path,
        mod.SyncDriver,
        postfinish_hooks={"action": {"s3_upload": ["*"], failing: ["*"]}},
    )
    try:
        _accept(drv)
        calls = []

        async def record(upath, rank=0, rank_limit=-5):
            calls.append((str(upath), rank))

        drv.enqueue_yml = record
        journal = []
        drv._journal = lambda yml_path, state: journal.append(state)
        exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1))
        act = make_action(exp_yml, 0)
        result = await asyncio.wait_for(drv.sync_yml(yml_path=act), timeout=15)
        assert isinstance(result, dict) and result["synced"] is True
        d = mod.Progress(act).dict
        assert (
            d["hooks"][failing]["state"] == "failed"
            and "push failed" in d["hooks"][failing]["error"]
        )
        assert mod.HelaoYml(act).status == "synced"
        assert journal == [DONE]
        assert (str(exp_yml), 1) in calls
        assert "push failed" in caplog.text
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_legacy_complete_prg_runs_nothing(tmp_path, mod):
    """A record synced before the hooks existed (s3+api, no `synced` key) is
    complete: sync_yml returns True at the already-synced gate, the chain never
    starts (no hooks/synced keys appear), and a blocking hook that would have
    failed the record is never reached."""
    failing = _hook_file(tmp_path, "would_fail", FAILING_HOOK.format(blocking="True"))
    drv = make_sync_driver(
        tmp_path,
        mod.SyncDriver,
        postfinish_hooks={"action": {"s3_upload": ["*"], failing: ["*"]}},
    )
    try:
        act = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        before = f"yml: {act}\napi: true\ns3: true\nfiles_pending: []\nfiles_s3: {{}}\n"
        act.with_suffix(".prg").write_text(before)
        assert await asyncio.wait_for(drv.sync_yml(yml_path=act), timeout=15) is True
        assert act.with_suffix(".prg").read_text() == before
        assert mod.HelaoYml(act).status == "synced"
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_dispatch_analysis_at_experiment_level_sends_experiment_path(
    tmp_path, mod, monkeypatch
):
    sent = []

    async def fake_dispatch(world_config_dict=None, A=None, **kw):
        sent.append((world_config_dict, A))
        return {}, None

    monkeypatch.setattr(dispatcher_mod, "async_action_dispatcher", fake_dispatch)
    ana = {
        "server_key": "ANA",
        "host": "127.0.0.1",
        "port": 1,
        "endpoint": "ana_exp",
        "params": {"q": 2},
    }
    drv = make_sync_driver(
        tmp_path,
        mod.SyncDriver,
        postfinish_hooks={
            "experiment": {"s3_upload": ["*"], "dispatch_analysis": {"test_exp": ana}}
        },
    )
    try:
        _accept(drv)
        _no_requeue(drv)
        exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1))
        result = await asyncio.wait_for(
            drv.sync_yml(yml_path=exp_yml, rank=1), timeout=15
        )
        assert isinstance(result, dict)
        assert len(sent) == 1
        world, A = sent[0]
        assert world == {"servers": {"ANA": ana}}
        assert A.action_name == "ana_exp"
        assert A.action_params == {
            "experiment_path": str(exp_yml.parent),
            "params": {"q": 2},
        }
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_dispatch_analysis_without_host_port_resolves_world_config_or_raises(
    tmp_path, mod
):
    drv = make_sync_driver(
        tmp_path,
        mod.SyncDriver,
        postfinish_hooks={
            "sequence": {
                "dispatch_analysis": {
                    "test_seq": {"server_key": "ANA", "endpoint": "e"}
                }
            }
        },
    )
    try:
        _no_requeue(drv)
        exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1))
        seq_yml = exp_yml.parent.parent / f"{ts(0)}-seq.yml"
        write_yml(seq_yml, {"sequence_uuid": mk_uuid(999), "sequence_name": "test_seq"})
        # the exp under it is unsynced -> the sequence gate re-queues; write a
        # legacy-complete prg for it so the sequence proceeds to its chain.
        exp_yml.with_suffix(".prg").write_text(f"yml: {exp_yml}\napi: true\ns3: true\n")
        await asyncio.wait_for(drv.sync_yml(yml_path=seq_yml, rank=2), timeout=15)
        d = mod.Progress(seq_yml).dict
        assert d["hooks"]["dispatch_analysis"]["state"] == "failed"
        assert "ANA" in d["hooks"]["dispatch_analysis"]["error"]
        assert d["synced"] is True  # non-blocking; the chain has no blocking hook
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_dispatch_analysis_refused_at_action_level(tmp_path, mod):
    with pytest.raises(HookConfigError) as ei:
        make_sync_driver(
            tmp_path,
            mod.SyncDriver,
            postfinish_hooks={
                "action": {
                    "dispatch_analysis": {"a": {"server_key": "A", "endpoint": "e"}}
                }
            },
        )
    assert "dispatch_analysis" in str(ei.value)
