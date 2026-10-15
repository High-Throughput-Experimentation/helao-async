"""Low-severity latent-crash fixes in the test deployment (fakes only)."""

import asyncio
import importlib
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from bokeh.document import Document

from helao.core.error import ErrorCodes

SERV_KEY = "SIM"


class _FakeVis:
    def __init__(self, doc):
        self.doc = doc
        self.server_cfg = {"params": {}}
        self.world_cfg = {"servers": {SERV_KEY: {"host": "127.0.0.1", "port": 8010}}}


def _build(modname):
    module = importlib.import_module(f"helao.deploy.test.servers.visualizer.{modname}")
    vis = module.C_vis(_FakeVis(Document()), SERV_KEY)
    vis.IOloop_data_run = False
    vis.IOtask.cancel()
    return vis


def test_wssim_plots_every_series_not_just_four():
    async def _run():
        vis = _build("wssim_live_vis")
        vis._add_plots()
        n_series = len([k for k in vis.data_dict_keys if k != "datetime"])
        assert n_series > 4 and len(vis.plot.renderers) == n_series

    asyncio.run(_run())


def test_gpsim_fifth_plate_does_not_raise():
    async def _run():
        vis = _build("gpsim_live_vis")
        quad = ([1.0, 2.0], [0.0, 1.0, 2.0], 2, [1.0, 2.0], [0.0, 1.0, 2.0], 2)
        vis.hists = {i: quad for i in range(5)}
        vis._add_plots()
        assert len(vis.plot.renderers) == 10

    asyncio.run(_run())


def test_demo_helper_exits_nonzero_on_a_bad_argument(monkeypatch):
    helper = Path(__file__).parents[1] / "demos" / "multi_orch_demo_helper.py"
    monkeypatch.setattr(sys, "argv", [str(helper), "demo9"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(helper), run_name="__main__")
    assert exc.value.code == 1


def test_query_plate_with_no_matching_plate_finishes_with_an_error(monkeypatch):
    from helao.deploy.test.servers.action import archive_simulator as mod

    routes = {}

    class _Host:
        def __init__(self, *a, **k):
            self.server_params = {}
            self.driver = SimpleNamespace(
                list_spaces=lambda: [
                    {"solution_ph": 7, "elements": ["Ni"], "plate_id": 1}
                ]
            )

        def action(self, **k):
            def deco(fn):
                routes[fn.__name__] = fn
                return fn

            return deco

        def post(self, *a, **k):
            return lambda fn: fn

    monkeypatch.setattr(mod, "ActionHost", _Host)
    mod.makeApp("K")
    action = SimpleNamespace(
        action_params={"ph": 13, "elements": ["Ni", "Fe"]}, error_code=ErrorCodes.none
    )
    action.as_dict = lambda: {"error_code": action.error_code}

    async def finish():
        return action

    async def begin(**k):
        return SimpleNamespace(action=action, finish=finish)

    out = asyncio.run(routes["query_plate"](SimpleNamespace(begin=begin)))
    assert out == {"error_code": ErrorCodes.not_available}
