"""Chain execution semantics (spec §6.2), on a real Progress over a tmp tree."""

from types import SimpleNamespace

import pytest

import helao.core.drivers.data.sync_driver as legacy_mod
import helao.hexagon.adapters.native.sync_driver as native_mod
from helao.core.hooks import FinishHook, HookSet
from helao.core.hooks.postfinish import run_postfinish_chain
from helao.hexagon.tests.sync_fixtures import make_action, make_exp_tree, mk_uuid


class _Hook(FinishHook):
    def __init__(self, blocking=True, fail=False):
        self.blocking, self.fail, self.calls = blocking, fail, 0

    async def run(self, ctx):
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"nope {self.calls}")
        ctx.prg.dict.setdefault("touched", []).append(ctx.args)


def _syncer(action_chain: dict[str, FinishHook], cfg: dict):
    return SimpleNamespace(
        postfinish={
            "action": HookSet(cfg=cfg, hooks=action_chain),
            "experiment": HookSet.empty(),
            "sequence": HookSet.empty(),
        }
    )


def _prog(tmp_path, mod):
    act = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
    return mod.Progress(act)


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_all_done_marks_synced_and_records_states(tmp_path, mod):
    a, b = _Hook(), _Hook(blocking=False)
    syncer = _syncer(
        {"a": a, "b": b}, {"a": {"*": {"x": 1}}, "b": {"test_action": None}}
    )
    prog = _prog(tmp_path, mod)
    assert await run_postfinish_chain(syncer, prog, opts={"compress": False}) is True
    on_disk = mod.Progress(prog.prg).dict
    assert on_disk["synced"] is True
    assert (
        on_disk["hooks"]["a"]["state"] == "done" and "T" in on_disk["hooks"]["a"]["ts"]
    )
    assert on_disk["hooks"]["b"]["state"] == "done"
    assert on_disk["touched"] == [{"x": 1}, None]


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_blocking_failure_stops_chain_and_resumes_at_failed_hook(tmp_path, mod):
    a, b, c = _Hook(), _Hook(fail=True), _Hook()
    syncer = _syncer({"a": a, "b": b, "c": c}, {k: {"*": None} for k in "abc"})
    prog = _prog(tmp_path, mod)
    assert await run_postfinish_chain(syncer, prog, opts={}) is False
    d = mod.Progress(prog.prg).dict
    assert d["synced"] is False
    assert d["hooks"]["a"]["state"] == "done"
    assert d["hooks"]["b"] == {
        "state": "failed",
        "ts": d["hooks"]["b"]["ts"],
        "error": "RuntimeError: nope 1",
    }
    assert "c" not in d["hooks"] and c.calls == 0
    # next pass: a is not re-run, b is retried and now succeeds, c runs
    b.fail = False
    assert await run_postfinish_chain(syncer, mod.Progress(prog.prg), opts={}) is True
    d = mod.Progress(prog.prg).dict
    assert (a.calls, b.calls, c.calls) == (1, 2, 1)
    assert d["synced"] is True and d["hooks"]["b"]["state"] == "done"
    assert "error" not in d["hooks"]["b"]


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_non_blocking_failure_is_recorded_alerted_and_does_not_block_synced(
    tmp_path, mod, caplog
):
    a, b, c = _Hook(), _Hook(blocking=False, fail=True), _Hook()
    syncer = _syncer({"a": a, "b": b, "c": c}, {k: {"*": None} for k in "abc"})
    prog = _prog(tmp_path, mod)
    assert await run_postfinish_chain(syncer, prog, opts={}) is True
    d = mod.Progress(prog.prg).dict
    assert d["synced"] is True and c.calls == 1
    assert d["hooks"]["b"]["state"] == "failed" and "nope 1" in d["hooks"]["b"]["error"]
    assert "b" in caplog.text
    # not retried automatically on the next pass (spec 6.2)
    assert await run_postfinish_chain(syncer, mod.Progress(prog.prg), opts={}) is True
    assert b.calls == 1
    # clearing the entry re-arms it
    p = mod.Progress(prog.prg)
    del p.dict["hooks"]["b"]
    p.write_dict()
    b.fail = False
    assert await run_postfinish_chain(syncer, mod.Progress(prog.prg), opts={}) is True
    assert b.calls == 2 and mod.Progress(prog.prg).dict["hooks"]["b"]["state"] == "done"


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_hooks_and_synced_false_are_written_before_the_first_hook_runs(
    tmp_path, mod
):
    class Peek(FinishHook):
        async def run(self, ctx):
            self.on_disk = mod.Progress(ctx.prg.prg).dict

    peek = Peek()
    syncer = _syncer({"peek": peek}, {"peek": {"*": None}})
    prog = _prog(tmp_path, mod)
    assert "hooks" not in prog.dict and "synced" not in prog.dict
    await run_postfinish_chain(syncer, prog, opts={})
    assert peek.on_disk["hooks"] == {} and peek.on_disk["synced"] is False


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_empty_chain_is_synced(tmp_path, mod):
    syncer = _syncer({}, {})
    prog = _prog(tmp_path, mod)
    assert await run_postfinish_chain(syncer, prog, opts={}) is True
    assert mod.Progress(prog.prg).dict["synced"] is True


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_syncer_without_postfinish_raises_rather_than_reporting_synced(
    tmp_path, mod
):
    """A syncer lacking ``.postfinish`` must fail loudly, not report synced.

    The old code shrugged a missing ``postfinish`` attribute into an empty
    chain via ``getattr(syncer, "postfinish", None) or {}``, so a
    misconfigured syncer silently uploaded nothing while the record was
    still marked synced and journaled DONE.
    """
    syncer = SimpleNamespace()  # no .postfinish at all
    prog = _prog(tmp_path, mod)
    with pytest.raises(AttributeError):
        await run_postfinish_chain(syncer, prog, opts={})


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_hooks_null_in_prg_runs_the_chain_normally(tmp_path, mod):
    """A ``.prg`` whose ``hooks:`` line loaded as ``None`` must not crash.

    ``prog.dict.setdefault("hooks", {})`` returns ``None`` (not the default)
    when the key is already present with a null value, so the first
    ``states.get(...)`` call below used to raise ``AttributeError``.
    """
    a = _Hook()
    syncer = _syncer({"a": a}, {"a": {"*": None}})
    prog = _prog(tmp_path, mod)
    prog.dict["hooks"] = None
    prog.write_dict()
    prog = mod.Progress(prog.prg)
    assert await run_postfinish_chain(syncer, prog, opts={}) is True
    assert mod.Progress(prog.prg).dict["hooks"]["a"]["state"] == "done"


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_context_carries_yml_prg_syncer_args_opts(tmp_path, mod):
    seen = {}

    class Grab(FinishHook):
        async def run(self, ctx):
            seen.update(
                yml=ctx.yml,
                prg=ctx.prg,
                syncer=ctx.syncer,
                args=ctx.args,
                opts=ctx.opts,
            )

    syncer = _syncer({"g": Grab()}, {"g": {"*": {"k": "v"}}})
    prog = _prog(tmp_path, mod)
    await run_postfinish_chain(syncer, prog, opts={"force_s3": True})
    assert seen["prg"] is prog and seen["syncer"] is syncer
    assert seen["yml"].target == prog.yml.target
    assert seen["args"] == {"k": "v"} and seen["opts"] == {"force_s3": True}
