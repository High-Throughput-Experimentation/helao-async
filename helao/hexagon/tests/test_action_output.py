"""set_output and the params guard (spec §4.2, §4.7)."""

import asyncio
import logging

import pytest

import helao.hexagon.adapters.native.finalizer as native_finalizer_mod
from helao.core.models.hlostatus import HloStatus
from helao.hexagon.tests.native_fixtures import make_base, mk_action, mk_active


async def _no_move(action, base=None):
    pass


async def _session(tmp_path, **over):
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, _ = mk_active(base, action=mk_action(**over) if over else None)
    base.actives[active.action.action_uuid] = active
    base.aloop = asyncio.get_running_loop()
    active.data_logger = base.aloop.create_task(active.log_data_task())
    await asyncio.sleep(0.05)
    return base, active


def test_action_model_set_output_merges():
    a = mk_action()
    a.set_output(x=1)
    a.set_output(y=2, x=3)
    assert a.action_output == {"x": 3, "y": 2}


@pytest.mark.asyncio
async def test_session_set_output_targets_the_running_split(tmp_path, monkeypatch):
    monkeypatch.setattr(native_finalizer_mod, "move_dir", _no_move)
    _, active = await _session(tmp_path)
    prev_uuid = active.action.action_uuid
    await active.split(uuid_list=[])
    active.set_output(after_split=1)
    prev = next(a for a in active.action_list if a.action_uuid == prev_uuid)
    assert active.action.action_output["after_split"] == 1
    assert "after_split" not in prev.action_output
    active.data_logger.cancel()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_session_set_output_on_finished_action_warns(tmp_path, caplog):
    _, active = await _session(tmp_path)
    active.action.action_status = [HloStatus.finished]
    with caplog.at_level(logging.WARNING):
        active.set_output(late=1)
    assert active.action.action_output["late"] == 1
    assert "late" in caplog.text and "finished" in caplog.text
    active.data_logger.cancel()
    await asyncio.sleep(0.05)


class _Probe:
    concurrent = True

    def __init__(self, active):
        self.active = active
        self.seen = None

    async def _pre_exec(self):
        self.seen = dict(self.active.params_snapshot)
        raise RuntimeError("probe stops here")


@pytest.mark.asyncio
async def test_snapshot_is_taken_at_executor_start(tmp_path):
    _, active = await _session(tmp_path, action_params={"a": 1})
    assert active.params_snapshot is None
    active.action.action_params["normalized_after_begin"] = 2
    probe = _Probe(active)
    try:
        await active.executor_runner.action_loop_task(probe)
    except RuntimeError as exc:  # the loop may re-raise or record the setup failure
        assert "probe" in str(exc)
    assert probe.seen == {"a": 1, "normalized_after_begin": 2}
    active.data_logger.cancel()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_finish_warns_on_params_written_after_executor_start(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setattr(native_finalizer_mod, "move_dir", _no_move)
    _, active = await _session(tmp_path, action_params={"keep": 1, "changed": 1})
    active.params_snapshot = dict(active.action.action_params)
    active.action.action_params["changed"] = 2
    active.action.action_params["added"] = 3
    with caplog.at_level(logging.WARNING):
        await active.finish()
    msgs = [
        r.getMessage()
        for r in caplog.records
        if "wrote action_params" in r.getMessage()
    ]
    assert len(msgs) == 1
    assert "added" in msgs[0] and "changed" in msgs[0] and "keep" not in msgs[0]
    assert "set_output" in msgs[0]


@pytest.mark.asyncio
async def test_finish_is_silent_without_snapshot_or_changes(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setattr(native_finalizer_mod, "move_dir", _no_move)
    _, active = await _session(tmp_path, action_params={"keep": 1})
    active.action.action_params["added_no_executor"] = 1  # no snapshot: unguarded
    with caplog.at_level(logging.WARNING):
        await active.finish()
    assert "wrote action_params" not in caplog.text


class _NoCopy:
    def __deepcopy__(self, memo):
        raise TypeError("cannot copy")


class _ProbeNone(_Probe):
    async def _pre_exec(self):
        self.seen = self.active.params_snapshot
        self.reached = True
        raise RuntimeError("probe stops here")


@pytest.mark.asyncio
async def test_uncopyable_param_does_not_kill_the_loop(tmp_path, monkeypatch):
    import helao.hexagon.app.executor_runner as er

    warned = []
    monkeypatch.setattr(er.LOGGER, "warning", lambda m, *a, **k: warned.append(m))
    _, active = await _session(tmp_path, action_params={"a": _NoCopy()})
    probe = _ProbeNone(active)
    try:
        await active.executor_runner.action_loop_task(probe)
    except RuntimeError as exc:
        assert "probe" in str(exc)
    assert probe.reached and probe.seen is None
    assert len(warned) == 1 and str(active.action.action_uuid) in warned[0]
    assert "cannot copy" in warned[0]
    active.data_logger.cancel()
    await asyncio.sleep(0.05)
