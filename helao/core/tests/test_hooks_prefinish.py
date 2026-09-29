"""Pre-finish flow (spec §5, D6, §5.2)."""

from pathlib import Path

import pytest

from helao.core.hooks import FinishHook, HookSet
from helao.core.hooks.prefinish import run_prefinish
from helao.helpers.premodels import Action, Experiment, Sequence


class _Ok(FinishHook):
    def __init__(self, log, tag):
        self.log, self.tag = log, tag

    async def run(self, ctx):
        self.log.append((self.tag, ctx.args))
        ctx.record.experiment_params[self.tag] = True


class _Boom(FinishHook):
    async def run(self, ctx):
        raise RuntimeError("kaboom")


def _exp(name="exp1"):
    exp = Experiment(experiment_name=name, experiment_params={})
    exp.init_exp(time_offset=0)
    return exp


def test_prefinish_errors_default_is_omitted_from_clean_dict():
    for model in (
        Action(action_name="a"),
        Experiment(experiment_name="e"),
        Sequence(sequence_name="s"),
    ):
        assert model.prefinish_errors == []
        assert "prefinish_errors" not in model.clean_dict()


@pytest.mark.asyncio
async def test_runs_matching_hooks_in_config_order_with_args():
    log = []
    hs = HookSet(
        cfg={
            "second": {"exp1": {"n": 2}},
            "skip": {"other": None},
            "first": {"*": None},
        },
        hooks={
            "second": _Ok(log, "second"),
            "skip": _Ok(log, "skip"),
            "first": _Ok(log, "first"),
        },
    )
    exp = _exp()
    await run_prefinish(hs, exp, "exp1", Path("/tmp/x"), server=object())
    assert log == [("second", {"n": 2}), ("first", None)]
    assert exp.experiment_params == {"second": True, "first": True}
    assert exp.prefinish_errors == []


@pytest.mark.asyncio
async def test_raising_hook_is_recorded_and_chain_continues(caplog):
    log = []
    hs = HookSet(
        cfg={"boom": {"*": None}, "after": {"*": None}},
        hooks={"boom": _Boom(), "after": _Ok(log, "after")},
    )
    exp = _exp()
    await run_prefinish(hs, exp, "exp1", Path("/tmp/x"), server=object())
    assert log == [("after", None)]
    assert len(exp.prefinish_errors) == 1
    err = exp.prefinish_errors[0]
    assert err["hook"] == "boom"
    assert err["error"] == "RuntimeError: kaboom"
    assert isinstance(err["ts"], str) and "T" in err["ts"]
    assert (
        "boom" in caplog.text
        and "exp1" in caplog.text
        and str(exp.experiment_uuid) in caplog.text
    )
    # the error travels with the record's yml/meta and nothing else changed
    assert exp.clean_dict()["prefinish_errors"] == exp.prefinish_errors


@pytest.mark.asyncio
async def test_empty_hookset_is_a_noop():
    exp = _exp()
    await run_prefinish(HookSet.empty(), exp, "exp1", Path("/tmp/x"), server=object())
    assert exp.prefinish_errors == []
