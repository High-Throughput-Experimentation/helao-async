"""E-STOP must reach the drivers, end to end on the native OrchHost.

Every driver's ``estop(switch)`` acts only when ``switch`` is True, so an
orchestrator that fans ``estop=False`` out on E-STOP never moves a driver. The
hexagon orchestrator does not call ``EstopController.estop_loop``: it goes
``OrchHost.estop_loop`` -> reducer (``EstopFanout``) -> effect runner ->
``estop_actions``. This pins the value that actually leaves the process.
"""

import asyncio

import pytest

from helao.hexagon.domain.models import LoopStatus
from helao.hexagon.tests.live_group import (
    build_ws_sequence,
    live_group,
    orch_call,
)


@pytest.mark.asyncio
async def test_estop_fans_out_true_and_clear_fans_out_false(tmp_path, monkeypatch):
    import helao.helpers.dispatcher as dispatcher_mod  # B7a: the seam lives here

    real = dispatcher_mod.async_action_dispatcher
    sent = []

    async def spy(world_cfg, A, *args, **kwargs):
        if A.action_name != "estop":
            return await real(world_cfg, A, *args, **kwargs)
        sent.append((A.action_params.get("switch"), (kwargs.get("params") or {})))
        return None

    monkeypatch.setattr(dispatcher_mod, "async_action_dispatcher", spy)

    async with live_group(str(tmp_path)) as g:
        orch = g.orch
        seq = build_ws_sequence(2, wait_time=1.0, data_duration=2.0)
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")
        for _ in range(200):
            if orch.globalstatusmodel.loop_state == LoopStatus.started:
                break
            await asyncio.sleep(0.05)
        assert orch.globalstatusmodel.loop_state == LoopStatus.started

        await orch.estop_loop("drill")
        assert orch.globalstatusmodel.loop_state == LoopStatus.estopped
        assert sent, "E-STOP fanned out to no server"
        assert all(
            switch is True and params == {"switch": True} for switch, params in sent
        ), sent

        n_estop = len(sent)
        await orch.clear_estop()
        assert orch.globalstatusmodel.loop_state == LoopStatus.stopped
        released = sent[n_estop:]
        assert released, "clear_estop fanned out to no server"
        assert all(
            switch is False and params == {"switch": False}
            for switch, params in released
        ), released


@pytest.mark.asyncio
async def test_real_transport_delivers_a_bool_switch_to_the_driver(tmp_path):
    """No dispatcher spy: the orchestrator's real fan-out (ZMQ RPC first, HTTP
    fallback) reaches the SIM server's real ``/SIM/estop`` route, and the
    driver's ``estop`` sees a bool ``True`` for E-STOP and ``False`` for clear."""
    async with live_group(str(tmp_path)) as g:
        received = []

        async def driver_estop(switch, *args, **kwargs):
            received.append(switch)
            return switch

        g.sim_app.driver.estop = driver_estop
        orch = g.orch
        seq = build_ws_sequence(2, wait_time=1.0, data_duration=2.0)
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")
        for _ in range(200):
            if orch.globalstatusmodel.loop_state == LoopStatus.started:
                break
            await asyncio.sleep(0.05)
        assert orch.globalstatusmodel.loop_state == LoopStatus.started

        await orch.estop_loop("drill")
        assert received == [True] and type(received[0]) is bool, received

        await orch.clear_estop()
        assert received == [True, False], received
        assert type(received[1]) is bool
