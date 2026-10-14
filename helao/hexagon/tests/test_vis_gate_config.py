"""Gate-config checks for the two bokeh-hosting configs, `goldenhexvis.yml` and
`goldenhexgraft.yml`. Both name the hte bokeh modules directly (no routing key);
they resolve, validate, and import-resolve, and every hte visualizer module
imports without hardware/vendor runtime."""

import os
import types
from importlib import import_module

import pytest

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
_CFG = os.path.join(
    _REPO_ROOT, "helao", "deploy", "test", "configs", "goldenhexvis.yml"
)
_GRAFT_CFG = os.path.join(
    _REPO_ROOT, "helao", "deploy", "test", "configs", "goldenhexgraft.yml"
)


def _load(path=_CFG):
    from helao.helpers.config_loader import read_config

    return read_config(path)


def _bokeh_entries(conf):
    return {
        k: v for k, v in conf["servers"].items() if isinstance(v, dict) and "bokeh" in v
    }


@pytest.mark.parametrize("path", [_CFG, _GRAFT_CFG])
def test_gate_configs_validate(path):
    from launch import validateConfig

    conf = _load(path)
    pidd = types.SimpleNamespace(
        reqKeys=("host", "port", "group"), codeKeys=("fast", "bokeh")
    )
    assert validateConfig(pidd, conf, _REPO_ROOT) is True


@pytest.mark.parametrize("path", [_CFG, _GRAFT_CFG])
def test_gate_bokeh_entries_name_hte_modules_with_no_routing_key(path):
    """Every bokeh server names its hte module directly: no `deployment` /
    `legacy_module` routing key, no `bokeh_port`, and the module resolves under
    helao.deploy.hte and exposes makeBokehApp."""
    bokeh_entries = _bokeh_entries(_load(path))
    assert set(bokeh_entries) == {"OPERATOR", "LIVE", "ACTVIS"}
    for scfg in bokeh_entries.values():
        assert "deployment" not in scfg
        assert "legacy_module" not in scfg
        assert "bokeh_port" not in scfg  # bokeh servers use host/port
        mod = import_module(f"helao.deploy.hte.servers.{scfg['group']}.{scfg['bokeh']}")
        assert callable(mod.makeBokehApp)


@pytest.mark.parametrize("path", [_CFG, _GRAFT_CFG])
def test_gate_configs_preflight_clean(path):
    from helao.hexagon import preflight

    assert preflight.preflight_config(path) == []


@pytest.mark.parametrize("path", [_CFG, _GRAFT_CFG])
def test_gate_config_ws_sources_present(path):
    """The operator needs ORCH ws_status, live vis needs SIM ws_live — the
    action/orch group must be in the gate config (reviewer point 3)."""
    conf = _load(path)
    servers = conf["servers"]
    # no server carries a routing key: every host is natively an ActionHost
    assert all("deployment" not in v for v in servers.values())
    assert servers["SIM"]["live_vis"] == "wssim_live_vis"
    assert servers["OPERATOR"]["params"]["orch_key"] == "ORCH"
    hostports = [
        (v["host"], v["port"]) for v in servers.values() if isinstance(v, dict)
    ]
    assert len(hostports) == len(set(hostports))


_VIS_DIR = os.path.join(_REPO_ROOT, "helao", "deploy", "hte", "servers", "visualizer")
_VIS_MODULES = [
    f"helao.deploy.hte.servers.visualizer.{f[:-3]}"
    for f in sorted(os.listdir(_VIS_DIR))
    if f.endswith(".py") and f != "__init__.py"
]


def test_vis_module_set_nonempty():
    stems = {m.rsplit(".", 1)[1] for m in _VIS_MODULES}
    expected = {"action_visualizer", "live_visualizer", "control_visualizer"}
    assert expected <= stems, sorted(expected - stems)


@pytest.mark.parametrize("mod", _VIS_MODULES)
def test_hte_vis_imports_on_linux(mod):
    """Every hte visualizer module imports without hardware/vendor runtime."""
    import_module(mod)
