"""P2d gate-config checks: goldenhexvis.yml resolves, validates, and every
bokeh entry's `deployment: hexagon` dotted path import-resolves to a shim
exporting makeBokehApp — the same path bokeh_launcher.py builds."""

import os
import types
from importlib import import_module

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
_CFG = os.path.join(
    _REPO_ROOT, "helao", "deploy", "test", "configs", "goldenhexvis.yml"
)


def _load():
    from helao.helpers.config_loader import read_config

    return read_config(_CFG)


def test_goldenhexvis_validates():
    from launch import validateConfig

    conf = _load()
    pidd = types.SimpleNamespace(
        reqKeys=("host", "port", "group"), codeKeys=("fast", "bokeh")
    )
    assert validateConfig(pidd, conf, _REPO_ROOT) is True


def test_goldenhexvis_bokeh_entries_are_hexagon_shims():
    conf = _load()
    bokeh_entries = {
        k: v for k, v in conf["servers"].items() if isinstance(v, dict) and "bokeh" in v
    }
    assert set(bokeh_entries) == {"OPERATOR", "LIVE", "ACTVIS"}
    for key, scfg in bokeh_entries.items():
        assert scfg["deployment"] == "hexagon"
        assert "bokeh_port" not in scfg  # bokeh servers use host/port
        modpath = (
            f"helao.deploy.{scfg['deployment']}.servers."
            f"{scfg['group']}.{scfg['bokeh']}"
        )  # bokeh_launcher.py:157-159 shape
        mod = import_module(modpath)
        assert callable(mod.makeBokehApp)
        assert mod.LEGACY_MODULE.startswith("helao.deploy.hte.servers.")


def test_goldenhexvis_ws_sources_present():
    """The operator needs ORCH ws_status, live vis needs SIM ws_live — the
    hexagon action/orch group must be in the gate config (reviewer point 3)."""
    conf = _load()
    servers = conf["servers"]
    assert servers["ORCH"]["deployment"] == "hexagon"
    assert servers["SIM"]["deployment"] == "hexagon"
    assert servers["SIM"]["live_vis"] == "wssim_live_vis"
    assert servers["OPERATOR"]["params"]["orch_key"] == "ORCH"
    hostports = [
        (v["host"], v["port"]) for v in servers.values() if isinstance(v, dict)
    ]
    assert len(hostports) == len(set(hostports))
