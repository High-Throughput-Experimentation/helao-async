"""Low-severity Bokeh visualizer fixes: co2 rolling mean source, mfc control_mode, nidaqmx reset."""

import asyncio
import importlib
import types

from bokeh.document import Document

from helao.deploy.hte.tests.test_pstat_vis_axis_selectors import (
    SERV_KEY,
    _build,
    _field,
    _FakeVis,
)

VIS = "helao.deploy.hte.servers.visualizer."


def _pkg(action_name, uuid, data, status=None):
    return types.SimpleNamespace(
        action_name=action_name,
        action_uuid=uuid,
        datamodel=types.SimpleNamespace(status=status, data={"u": data}),
    )


def test_co2_rolling_mean_line_is_bound_to_the_datasource():
    vis = _build(importlib.import_module(VIS + "co2_vis"))
    vis._add_plots()
    by_y = {_field(r.glyph.y): r.data_source for r in vis.plot.renderers}
    assert by_y["co2_ppm_mean"] is vis.datasource


def test_mfc_empty_batch_does_not_raise():
    mod = importlib.import_module(VIS + "mfc_vis")
    host = _FakeVis(Document())
    host.world_cfg = {
        "servers": {
            SERV_KEY: {
                "host": "127.0.0.1",
                "port": 8004,
                "params": {"devices": {"d1": {}}},
            }
        }
    }

    async def _make():
        vis = mod.C_vis(host, SERV_KEY)
        vis.IOloop_data_run = False
        vis.IOtask.cancel()
        return vis

    vis = asyncio.run(_make())
    vis.add_points([])  # an empty batch has no control_point column either
    assert vis.control_mode == "mass flow"


def _row(vis, t_s):
    return {k: [t_s] for k in vis.data_dict_keys}


def test_nidaqmx_foreign_action_does_not_reset_the_live_plot():
    mod = importlib.import_module(VIS + "nidaqmx_vis")
    vis = _build(mod)
    action = mod.VALID_ACTION_NAME[0]
    vis.add_points([_pkg(action, "uuid-cell", _row(vis, 1.0))])
    assert vis.cur_action_uuid == "uuid-cell"
    vis.add_points([_pkg("acquire_monitors", "uuid-mon", _row(vis, 9.0))])
    assert vis.cur_action_uuid == "uuid-cell"
    assert vis.datasource.data["t_s"] == [1.0]
