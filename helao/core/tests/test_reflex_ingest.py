"""Tests for the Reflex UI stack's WebSocket ingest layer."""

import asyncio
import pickle

import numpy as np
import pyzstd
import pytest
import websockets

from helao.core.servers.reflex.ingest import (
    IngestRegistry,
    WsIngest,
    normalize,
)


def test_normalize_unwraps_value_epoch_tuples():
    cols, rows = normalize([{"co2_ppm": (410.0, 100.0)}])
    assert cols["co2_ppm"] == [410.0]
    assert cols["epoch"] == [100.0]


def test_normalize_flattens_sim_dict():
    cols, _ = normalize([{"sim_dict": ({"series_0": 1.0, "series_1": 2.0}, 5.0)}])
    assert cols["series_0"] == [1.0]
    assert cols["series_1"] == [2.0]
    assert cols["epoch"] == [5.0]


def test_normalize_extends_on_list_values():
    cols, _ = normalize([{"v": ([1.0, 2.0, 3.0], 7.0)}])
    assert cols["v"] == [1.0, 2.0, 3.0]


def test_normalize_uses_max_epoch_per_message():
    cols, _ = normalize([{"a": (1.0, 10.0), "b": (2.0, 30.0)}])
    assert cols["epoch"] == [30.0]


def test_normalize_routes_non_numeric_values_to_rows():
    cols, rows = normalize([{"orchestrator": ("ORCH", 1.0), "v": (2.0, 1.0)}])
    assert "orchestrator" not in cols
    assert rows == [{"orchestrator": "ORCH"}]
    assert cols["v"] == [2.0]


def test_normalize_handles_empty_input():
    cols, rows = normalize([])
    assert cols == {}
    assert rows == []


def test_normalize_ignores_malformed_entries():
    cols, _ = normalize([{"bad": "not a tuple", "good": (1.0, 2.0)}])
    assert cols["good"] == [1.0]
    assert "bad" not in cols


@pytest.mark.asyncio
async def test_wsingest_fills_buffer_from_a_live_server():
    async def handler(ws):
        for i in range(5):
            payload = {"v": (float(i), 100.0 + i)}
            await ws.send(pyzstd.compress(pickle.dumps(payload)))
            await asyncio.sleep(0.01)
        await asyncio.sleep(1.0)

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        ing = WsIngest("127.0.0.1", port, "")
        ing.start()
        try:
            for _ in range(200):
                if ing.buffer.length >= 5:
                    break
                await asyncio.sleep(0.02)
            snap = ing.buffer.snapshot()
            np.testing.assert_allclose(snap["v"], [0.0, 1.0, 2.0, 3.0, 4.0])
            assert ing.status.state == "live"
            assert ing.status.message_count >= 5
        finally:
            await ing.stop()


@pytest.mark.asyncio
async def test_wsingest_recovers_after_the_server_restarts():
    sent = {"n": 0}

    async def handler(ws):
        sent["n"] += 1
        await ws.send(pyzstd.compress(pickle.dumps({"v": (float(sent["n"]), 1.0)})))
        await ws.close()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        ing = WsIngest("127.0.0.1", port, "")
        ing.start()
        try:
            # WsSubscriber backs off 1s after a drop, so allow several seconds
            # for a second connection to land.
            for _ in range(400):
                if ing.buffer.length >= 2:
                    break
                await asyncio.sleep(0.02)
            assert ing.buffer.length >= 2, "subscriber did not reconnect"
        finally:
            await ing.stop()


@pytest.mark.asyncio
async def test_wsingest_stop_is_idempotent():
    ing = WsIngest("127.0.0.1", 1, "")
    ing.start()
    await ing.stop()
    await ing.stop()


def test_registry_discovers_targets_from_vis_config_keys():
    cfg = {
        "servers": {
            "SIM": {"host": "127.0.0.1", "port": 8002, "live_vis": "wssim_panel"},
            "OER": {"host": "127.0.0.1", "port": 8003, "action_vis": "oersim_panel"},
            "ORCH": {"host": "127.0.0.1", "port": 8001, "group": "orchestrator"},
        }
    }
    reg = IngestRegistry(cfg)
    assert sorted(reg.targets()) == [("OER", "ws_data"), ("SIM", "ws_live")]


def test_registry_accepts_a_list_of_vis_modules_without_duplicating_targets():
    cfg = {
        "servers": {
            "SIM": {
                "host": "127.0.0.1",
                "port": 8002,
                "live_vis": ["wssim_panel", "gpsim_panel"],
            }
        }
    }
    assert IngestRegistry(cfg).targets() == [("SIM", "ws_live")]


def test_registry_skips_servers_missing_host_or_port():
    cfg = {"servers": {"BAD": {"live_vis": "wssim_panel"}}}
    assert IngestRegistry(cfg).targets() == []


def test_registry_get_returns_none_for_unknown_target():
    reg = IngestRegistry({"servers": {}})
    assert reg.get("NOPE", "ws_live") is None
