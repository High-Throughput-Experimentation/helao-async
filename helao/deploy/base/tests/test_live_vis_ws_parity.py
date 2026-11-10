"""Wire-consumer conformance for the base `add_points` implementations
(`pressure_vis`, `temp_vis`), fed the decoded payload the real
`VisSubscriber.IOloop_data` would hand them, built from `harness/ws_frames`
(real encoder -> real WsSubscriber decoder, never a hand-built dict standing in
for the wire).

The helpers here are also used by hte's test_vis_ws_parity.py.
"""

import asyncio
import importlib
from pathlib import Path

import pytest
from bokeh.document import Document

from harness import ws_frames as wf
from helao.helpers.server_modules import import_path, module_file


class _FakeVis:
    """The attributes `VisSubscriber.__init__` reads, plus a document.

    `server_cfg["params"]` is the VIS server's own config (num_channels
    etc.); `world_cfg["servers"][key]["params"]` is the ACTION server's
    config (devices/dev_ai/dev_monitor etc.) -- two different injection
    points, per vis_subscriber.py:206 vs each panel's own
    `self.serv_config.get("params", ...)` reads.
    """

    def __init__(self, doc, vis_params=None, servers=None):
        self.doc = doc
        self.server_cfg = {"params": vis_params or {}}
        self.world_cfg = {"servers": servers or {}}


def _servers(serv_key: str, action_params: dict | None = None) -> dict:
    return {
        serv_key: {
            "host": "127.0.0.1",
            "port": 8004,
            "params": action_params or {},
        }
    }


def _build(module, serv_key: str, vis_params=None, action_params=None):
    """Construct a visualizer and stop its ingest task before it can open a
    socket to a server that is not there (recipe shared with
    test_pstat_vis_axis_selectors.py)."""
    vis = module.C_vis(
        _FakeVis(
            Document(), vis_params=vis_params, servers=_servers(serv_key, action_params)
        ),
        serv_key,
    )
    vis.IOloop_data_run = False
    vis.IOtask.cancel()
    return vis


async def _decoded_live(numeric: dict, strings: dict | None = None) -> dict:
    payload = wf.build_live_payload(numeric=numeric, strings=strings or {})
    _, decoded = await wf.roundtrip("ws_live", "base_api", payload=payload)
    return decoded


async def _decoded_data(numeric: dict, strings: dict, action_name: str) -> object:
    payload = wf.build_data_payload(
        numeric=numeric, strings=strings, action_name=action_name
    )
    _, decoded = await wf.roundtrip("ws_data", "base_api", payload=payload)
    return decoded


def _import(modname):
    path = module_file("base", modname, "bokeh")
    assert path is not None, modname
    return importlib.import_module(import_path(path))


def test_both_base_live_visualizers_define_add_points():
    servers = Path(__file__).resolve().parents[1] / "servers"
    found = {
        p.stem
        for p in servers.glob("visualizer/*.py")
        if "def add_points" in p.read_text(encoding="utf-8")
    }
    assert found == {"pressure_vis", "temp_vis"}, found


def test_temp_vis_ingests_recognized_and_raises_on_unrecognized():
    module = _import("temp_vis")

    async def _run():
        vis = _build(module, "TEMP0", action_params={"dev_monitor": {"TC0": {}}})
        assert vis.connected
        assert vis.data_dict_keys == ["datetime", "TC0"]
        before = len(vis.datasource.data["TC0"])
        decoded = await _decoded_live({"TC0": 22.5})
        vis.add_points([decoded])
        assert len(vis.datasource.data["TC0"]) == before + 1
        assert vis.datasource.data["TC0"][-1] == 22.5

        bad = await _decoded_live({}, strings={wf.LIVE_STRING_LABEL: "x"})
        with pytest.raises(KeyError):
            vis.add_points([bad])

    asyncio.run(_run())


def test_pressure_vis_ingests_recognized_and_raises_on_unrecognized():
    module = _import("pressure_vis")

    async def _run():
        vis = _build(module, "PRESSURE0", action_params={"dev_ai": {"AI0": {}}})
        assert vis.connected
        assert vis.ai_keys == ["AI0"]
        before = len(vis.datasource.data["AI0"])
        decoded = await _decoded_live({"AI0": 14.7})
        vis.add_points([decoded])
        assert len(vis.datasource.data["AI0"]) == before + 1
        assert vis.datasource.data["AI0"][-1] == 14.7
        # rolling-mean column self-computes to the same length, not raised
        assert len(vis.datasource.data["AI0_mean"]) == before + 1

        bad = await _decoded_live({}, strings={wf.LIVE_STRING_LABEL: "x"})
        with pytest.raises(KeyError):
            vis.add_points([bad])

    asyncio.run(_run())
