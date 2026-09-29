"""MicroOrch finish path (spec §7): roots, hooks, finish_yml, read-back."""

import os
from pathlib import Path

import pytest

import helao.core.runners.micro_orch as micro_mod
from helao.core.hooks import FinishHook, HookConfigError, HookSet
from helao.core.models.hlostatus import HloStatus
from helao.core.runners.micro_orch import MicroOrch
from helao.helpers.premodels import Experiment, Sequence
from helao.helpers.yml_tools import yml_load

SYNC = {"host": "127.0.0.1", "port": 8010, "group": "action", "fast": "sync_server"}
ORCH = {"group": "orchestrator", "prefinish_experiment_hooks": {"append_params": ["*"]}}


def _orch(root, servers=None, **kw) -> MicroOrch:
    return MicroOrch(
        server_key="micro",
        host="127.0.0.1",
        port=9999,
        world_cfg={"root": str(root), "servers": servers or {}},
        finished_timeout=2.0,
        poll_interval=0.05,
        **kw,
    )


def _exp(name="exp1", manual=False) -> Experiment:
    exp = Experiment(experiment_name=name, experiment_params={})
    if not manual:
        exp.sequence_name = "seq1"
        exp.sequence_label = "lbl"
        exp.init_seq(time_offset=0)
    else:
        exp.manual_action = True
        exp.sequence_name = f"seq--{name}"
        exp.sequence_label = "manual"
        exp.init_seq(time_offset=0)
    exp.init_exp(time_offset=0)
    return exp


class _Probe(FinishHook):
    def __init__(self):
        self.seen = []

    async def run(self, ctx):
        self.seen.append((ctx.record.experiment_name, str(ctx.record_dir)))
        ctx.record.experiment_params["hooked"] = True


def _patch_finisher(monkeypatch):
    calls = []

    async def fake(yml_path, sync_config={}, retry=3):
        calls.append((yml_path, sync_config))
        return True

    monkeypatch.setattr(micro_mod, "yml_finisher", fake)
    return calls


def test_record_roots(tmp_path):
    orch = _orch(tmp_path)
    assert orch._record_root(False) == str(tmp_path / "RUNS")
    assert orch._record_root(True) == str(tmp_path / "DIAG")


@pytest.mark.asyncio
async def test_finish_experiment_runs_hooks_writes_under_runs_and_hands_off(
    tmp_path, monkeypatch
):
    calls = _patch_finisher(monkeypatch)
    orch = _orch(tmp_path, servers={"SYNC": SYNC})
    probe = _Probe()
    orch.experiment_hooks = HookSet(
        cfg={"probe": {"exp1": None}}, hooks={"probe": probe}
    )
    exp = _exp()
    yml_path = await orch._finish_experiment(exp)
    assert yml_path.startswith(str(tmp_path / "RUNS") + os.sep)
    expected_dir = os.path.join(str(tmp_path / "RUNS"), exp.get_experiment_dir())
    assert probe.seen == [("exp1", expected_dir)]
    meta = yml_load(Path(yml_path).read_text())
    assert meta["experiment_params"] == {"hooked": True}
    assert "finished" in str(meta["experiment_status"])
    assert calls == [(yml_path, SYNC)]
    # read-back finds it in the new tree
    assert orch._candidate_yml(exp.get_experiment_dir(), "exp") == yml_path


@pytest.mark.asyncio
async def test_no_sync_server_means_no_handoff(tmp_path, monkeypatch):
    calls = _patch_finisher(monkeypatch)
    orch = _orch(tmp_path)
    await orch._finish_experiment(_exp())
    assert calls == []


@pytest.mark.asyncio
async def test_manual_experiment_lands_in_diag_and_is_not_handed_off(
    tmp_path, monkeypatch
):
    calls = _patch_finisher(monkeypatch)
    orch = _orch(tmp_path, servers={"SYNC": SYNC})
    exp = _exp("man", manual=True)
    yml_path = await orch._finish_experiment(exp)
    assert yml_path.startswith(str(tmp_path / "DIAG") + os.sep)
    assert calls == []
    assert orch._candidate_yml(exp.get_experiment_dir(), "exp") == yml_path


@pytest.mark.asyncio
async def test_finish_sequence_runs_hooks_and_hands_off(tmp_path, monkeypatch):
    calls = _patch_finisher(monkeypatch)
    orch = _orch(tmp_path, servers={"SYNC": SYNC})
    seen = []

    class SeqProbe(FinishHook):
        async def run(self, ctx):
            seen.append(ctx.record.sequence_name)

    orch.sequence_hooks = HookSet(cfg={"p": {"*": None}}, hooks={"p": SeqProbe()})
    seq = Sequence(sequence_name="seq1", sequence_label="lbl")
    seq.init_seq(time_offset=0)
    yml_path = await orch._finish_sequence(seq)
    assert seen == ["seq1"]
    assert yml_path.startswith(str(tmp_path / "RUNS") + os.sep)
    assert calls == [(yml_path, SYNC)]
    assert seq.sequence_status == [HloStatus.finished]


@pytest.mark.asyncio
async def test_start_loads_hooks_from_world_orchestrator_entry(tmp_path, monkeypatch):
    orch = _orch(tmp_path, servers={"ORCH": ORCH})

    async def no_serve(host, port):
        return None

    monkeypatch.setattr(orch.dispatcher, "serve", no_serve)
    assert orch.experiment_hooks.cfg == {}
    await orch.start()
    assert list(orch.experiment_hooks.cfg) == ["append_params"]
    assert orch.sequence_hooks.cfg == {}


@pytest.mark.asyncio
async def test_constructor_override_wins_and_bad_hook_fails_in_start(
    tmp_path, monkeypatch
):
    orch = _orch(
        tmp_path,
        servers={"ORCH": ORCH},
        prefinish_experiment_hooks={"nope_hook": ["*"]},
    )
    served = []

    async def no_serve(host, port):
        served.append(port)

    monkeypatch.setattr(orch.dispatcher, "serve", no_serve)
    with pytest.raises(HookConfigError):
        await orch.start()
    assert served == []  # validated before the dispatcher binds


@pytest.mark.asyncio
async def test_run_experiment_survives_unreachable_sync(tmp_path, monkeypatch):
    """Fix round 1: an unreachable SYNC must not crash run_experiment/run_sequence.

    yml_finisher only catches asyncio.TimeoutError; a connector-style exception
    (stand-in: OSError) must be caught in _notify_sync, logged, and swallowed so
    the already-written record is still loaded and tracked.
    """

    async def raising(yml_path, sync_config={}, retry=3):
        raise OSError("connection refused")  # stands in for ClientConnectorError

    monkeypatch.setattr(micro_mod, "yml_finisher", raising)
    orch = _orch(tmp_path, servers={"SYNC": SYNC})

    def _no_actions(experiment):
        return []

    # a non-manual experiment (parented under a real sequence) so _notify_sync
    # actually reaches yml_finisher instead of returning early on manual=True
    seq = Sequence(sequence_name="seq1", sequence_label="lbl")
    seq.init_seq(time_offset=0)
    loaded = await orch.run_experiment(
        _no_actions,
        experiment=Experiment(experiment_name="unreachable_sync"),
        _sequence=seq,
    )
    assert loaded.experiment_name == "unreachable_sync"
    assert any(r["type"] == "experiment" for r in orch.runs)


@pytest.mark.asyncio
async def test_track_run_state_is_runs_or_diag(tmp_path):
    orch = _orch(tmp_path)
    yml = (
        tmp_path
        / "RUNS"
        / "2026"
        / "0928"
        / "120000__seq1__lbl"
        / "260928.120000__exp1"
        / "x-exp.yml"
    )
    yml.parent.mkdir(parents=True)
    yml.write_text("file_type: experiment\n")
    rec = orch._track_run("experiment", "u", "exp1", str(yml))
    assert rec["state"] == "RUNS"
    assert rec["rel_dir"] == os.path.join(
        "2026", "0928", "120000__seq1__lbl", "260928.120000__exp1"
    )
