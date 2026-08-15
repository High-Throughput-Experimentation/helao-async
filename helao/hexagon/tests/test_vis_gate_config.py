"""Gate-config checks for the two hexagon bokeh-hosting configs.

`goldenhexvis.yml` (P2d) routes its bokeh servers through the three EXPLICIT
hexagon shims, each hardcoding a public `hte` legacy module. `goldenhexgraft.yml`
(P7e) moves two of the same servers onto the GENERIC `bokeh: graft` shim, whose
legacy target is a config value — the route a PRIVATE deployment must use,
since a shim naming it could not live in this public repo. Both configs
resolve, validate, and import-resolve along the exact path
bokeh_launcher.py:157-174 builds."""

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


def test_goldenhexvis_bokeh_entries_are_explicit_hexagon_shims():
    """P2d's config: every bokeh server rides a per-module hexagon shim that
    NAMES its legacy target in code. Kept as-is — the explicit shims stay the
    readable route for the public deployments, and this is the assertion that
    would catch one of them being silently repointed."""
    conf = _load()
    bokeh_entries = _bokeh_entries(conf)
    assert set(bokeh_entries) == {"OPERATOR", "LIVE", "ACTVIS"}
    for key, scfg in bokeh_entries.items():
        assert scfg["deployment"] == "hexagon"
        assert "bokeh_port" not in scfg  # bokeh servers use host/port
        assert scfg["bokeh"] != "graft"
        assert "legacy_module" not in scfg  # explicit shims need no config key
        modpath = (
            f"helao.deploy.{scfg['deployment']}.servers."
            f"{scfg['group']}.{scfg['bokeh']}"
        )  # bokeh_launcher.py:157-159 shape
        mod = import_module(modpath)
        assert callable(mod.makeBokehApp)
        assert mod.LEGACY_MODULE.startswith("helao.deploy.hte.servers.")


def test_goldenhexgraft_moves_the_target_from_code_into_config():
    """P7e's config: OPERATOR and LIVE ride the GENERIC graft, so the legacy
    module is named by the CONFIG and by nothing in this repo — the property a
    private deployment depends on. ACTVIS stays explicit, proving the two
    routes coexist in one group."""
    conf = _load(_GRAFT_CFG)
    bokeh_entries = _bokeh_entries(conf)
    assert set(bokeh_entries) == {"OPERATOR", "LIVE", "ACTVIS"}
    grafted = {k for k, v in bokeh_entries.items() if v["bokeh"] == "graft"}
    assert grafted == {"OPERATOR", "LIVE"}

    for key, scfg in bokeh_entries.items():
        assert scfg["deployment"] == "hexagon"
        assert "bokeh_port" not in scfg
        modpath = (
            f"helao.deploy.{scfg['deployment']}.servers."
            f"{scfg['group']}.{scfg['bokeh']}"
        )  # bokeh_launcher.py:157-159 shape
        mod = import_module(modpath)
        assert callable(mod.makeBokehApp)
        if key in grafted:
            # the shim names nothing; the config names everything
            assert not hasattr(mod, "LEGACY_MODULE")
            legacy = scfg["legacy_module"]
            assert legacy.startswith("helao.deploy.")
            # sibling of `bokeh:`, NOT a params entry — the wrapped legacy
            # makeBokehApp must see its original params unchanged
            assert "legacy_module" not in scfg.get("params", {})
            assert import_module(legacy).makeBokehApp is not None
        else:
            assert mod.LEGACY_MODULE.startswith("helao.deploy.hte.servers.")


@pytest.mark.parametrize("path", [_CFG, _GRAFT_CFG])
def test_gate_configs_preflight_clean(path):
    from helao.hexagon import preflight

    assert preflight.preflight_config(path) == []


@pytest.mark.parametrize("path", [_CFG, _GRAFT_CFG])
def test_gate_config_ws_sources_present(path):
    """The operator needs ORCH ws_status, live vis needs SIM ws_live — the
    hexagon action/orch group must be in the gate config (reviewer point 3)."""
    conf = _load(path)
    servers = conf["servers"]
    assert servers["ORCH"]["deployment"] == "hexagon"
    # SIM carries NO deployment key, and that is the assertion. The key routes
    # a server through the hexagon shim, which grafts over a legacy BaseAPI;
    # ws_simulator is now natively an ActionHost (test_ws_simulator_port), so
    # re-adding the key would send a native host back through a graft that has
    # nothing to rebind.
    assert "deployment" not in servers["SIM"]
    assert servers["SIM"]["live_vis"] == "wssim_live_vis"
    assert servers["OPERATOR"]["params"]["orch_key"] == "ORCH"
    hostports = [
        (v["host"], v["port"]) for v in servers.values() if isinstance(v, dict)
    ]
    assert len(hostports) == len(set(hostports))
