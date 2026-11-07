"""/estop_orch acts whenever there is anything to stop, not only when `started`.

After Stop (or when the last action has been dispatched) the loop reads
``stopped`` while the final experiment is still closing out with an action
running on hardware (``stopped`` is not "parked", see
``helao/hexagon/app/CLAUDE.md``). The route used to log "not running" and
return, so E-STOP did nothing at the moment the operator most needed it.
"""

import asyncio

import pytest

from helao.core.models.hlostatus import HloStatus
from helao.hexagon.domain.models import LoopStatus
from helao.hexagon.tests.live_group import build_ws_sequence, live_group, orch_call


def _spy_estop_sends(monkeypatch):
    import helao.helpers.dispatcher as dispatcher_mod

    real = dispatcher_mod.async_action_dispatcher
    sent = []

    async def spy(world_cfg, A, *args, **kwargs):
        if A.action_name != "estop":
            return await real(world_cfg, A, *args, **kwargs)
        sent.append((kwargs.get("params") or {}).get("switch"))
        return None

    monkeypatch.setattr(dispatcher_mod, "async_action_dispatcher", spy)
    return sent


@pytest.mark.asyncio
async def test_estop_orch_with_stopped_loop_and_active_actions_estops(
    tmp_path, monkeypatch
):
    from helao.core.models.machine import MachineModel
    from helao.helpers.premodels import Action

    sent = _spy_estop_sends(monkeypatch)
    async with live_group(str(tmp_path)) as g:
        gsm = g.orch.globalstatusmodel
        assert gsm.loop_state == LoopStatus.stopped
        a = Action(
            action_name="acquire_data",
            action_server=MachineModel(server_name="SIM", machine_name="h"),
            orchestrator=gsm.orchestrator,
        )
        gsm.active_dict[a.action_uuid] = a
        await orch_call("estop_orch")
        assert gsm.loop_state == LoopStatus.estopped
        assert sent and all(s is True for s in sent), sent


@pytest.mark.asyncio
async def test_estop_orch_with_active_experiment_only_estops(tmp_path, monkeypatch):
    from helao.helpers.premodels import Experiment

    sent = _spy_estop_sends(monkeypatch)
    async with live_group(str(tmp_path)) as g:
        g.orch.active_experiment = Experiment(experiment_name="closing_out")
        await orch_call("estop_orch")
        assert g.orch.globalstatusmodel.loop_state == LoopStatus.estopped
        assert sent and all(s is True for s in sent), sent


@pytest.mark.asyncio
async def test_operator_estop_with_nothing_running_still_latches_and_fans_out(
    tmp_path, monkeypatch
):
    """User ruling: the operator's E-STOP always latches and fans out, even
    when the orchestrator believes nothing runs (hardware moved by a manual
    or other-UI action must stop). Clear then releases the servers."""
    real_sent = _spy_estop_sends(monkeypatch)
    async with live_group(str(tmp_path)) as g:
        gsm = g.orch.globalstatusmodel
        assert gsm.loop_state == LoopStatus.stopped and not gsm.active_dict
        assert g.orch.active_experiment is None
        await orch_call("estop_orch")
        assert gsm.loop_state == LoopStatus.estopped
        assert real_sent and all(sw is True for sw in real_sent), real_sent
        n = len(real_sent)
        await orch_call("clear_estop")
        assert gsm.loop_state == LoopStatus.stopped
        assert len(real_sent) > n and all(sw is False for sw in real_sent[n:])


@pytest.mark.asyncio
async def test_operator_estop_latches_the_real_server_and_clear_releases_it(tmp_path):
    async with live_group(str(tmp_path)) as g:
        await orch_call("estop_orch")
        assert g.orch.globalstatusmodel.loop_state == LoopStatus.estopped
        assert g.sim_app.actionservermodel.estop is True
        await orch_call("clear_estop")
        assert g.orch.globalstatusmodel.loop_state == LoopStatus.stopped
        assert g.sim_app.actionservermodel.estop is False


@pytest.mark.asyncio
async def test_stale_dispatch_error_after_clear_does_not_relatch(tmp_path, monkeypatch):
    """orch_dispatch's error path calls ``orch.estop_loop``; arriving after
    E-STOP + Clear with nothing running it must not re-latch."""
    from helao.helpers.premodels import Experiment

    sent = _spy_estop_sends(monkeypatch)
    async with live_group(str(tmp_path)) as g:
        g.orch.active_experiment = Experiment(experiment_name="closing_out")
        await orch_call("estop_orch")
        await orch_call("clear_estop")
        assert g.orch.active_experiment is None
        n = len(sent)
        await g.orch.estop_loop("stale error result")
        assert g.orch.globalstatusmodel.loop_state == LoopStatus.stopped
        assert len(sent) == n


@pytest.mark.asyncio
async def test_estop_orch_while_already_estopped_does_not_refan(tmp_path, monkeypatch):
    from helao.helpers.premodels import Experiment

    sent = _spy_estop_sends(monkeypatch)
    async with live_group(str(tmp_path)) as g:
        g.orch.active_experiment = Experiment(experiment_name="closing_out")
        await orch_call("estop_orch")
        n = len(sent)
        assert n
        g.orch.active_experiment = Experiment(experiment_name="again")
        await orch_call("estop_orch")
        assert len(sent) == n


@pytest.mark.asyncio
async def test_estop_while_final_action_runs_after_loop_stopped(tmp_path):
    """The real window: every action dispatched, loop `stopped`, the last SIM
    acquisition still running and the experiment closing out."""
    async with live_group(str(tmp_path)) as g:
        orch = g.orch
        gsm = orch.globalstatusmodel
        seq = build_ws_sequence(1, wait_time=0.5, data_duration=25.0)
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")

        def closing_out():
            return (
                gsm.loop_state == LoopStatus.stopped
                and orch.active_experiment is not None
                and any(
                    a.action_name == "acquire_data" for a in gsm.active_dict.values()
                )
            )

        deadline = asyncio.get_event_loop().time() + 40
        while not closing_out():
            assert asyncio.get_event_loop().time() < deadline, (
                f"never reached close-out: {gsm.loop_state} "
                f"{[a.action_name for a in gsm.active_dict.values()]}"
            )
            await asyncio.sleep(0.05)

        await orch_call("estop_orch")
        assert gsm.loop_state == LoopStatus.estopped
        # the running SIM action ends well before its 25 s duration
        t0 = asyncio.get_event_loop().time()
        while gsm.active_dict:
            assert asyncio.get_event_loop().time() - t0 < 10, (
                "action still running after E-STOP: "
                f"{[a.action_name for a in gsm.active_dict.values()]}"
            )
            await asyncio.sleep(0.1)
        assert orch.active_experiment is None
        # the latch survives the drain, the action ended estopped, and Clear works
        await asyncio.sleep(2.0)
        assert gsm.loop_state == LoopStatus.estopped
        estopped = {
            str(u) for u in gsm.find_hlostatus_in_finished(HloStatus.estopped)
        } | {
            str(u)
            for u, m in orch.action_history.items()
            if HloStatus.estopped in (m.get("action_status") or [])
        }
        assert estopped, "the SIM action never reported estopped"
        await orch_call("clear_estop")
        assert gsm.loop_state == LoopStatus.stopped
