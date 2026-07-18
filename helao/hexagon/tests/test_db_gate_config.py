"""P2e gate-config checks (D3): every goldenhex-family config routes DB
through `deployment: hexagon`, the dotted path import-resolves to the P2e
shim (same shape fast_launcher builds), and the config still validates.
Mirrors test_vis_gate_config.py."""

import os
import types
from importlib import import_module

import pytest

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
_CFG_DIR = os.path.join(_REPO_ROOT, "helao", "deploy", "test", "configs")
_FAMILY = ["goldenhex", "goldenhexid", "goldenhexconc", "goldenhexvis"]


def _load(prefix):
    from helao.helpers.config_loader import read_config

    return read_config(os.path.join(_CFG_DIR, f"{prefix}.yml"))


@pytest.mark.parametrize("prefix", _FAMILY)
def test_config_validates(prefix):
    from launch import validateConfig

    conf = _load(prefix)
    pidd = types.SimpleNamespace(
        reqKeys=("host", "port", "group"), codeKeys=("fast", "bokeh")
    )
    assert validateConfig(pidd, conf, _REPO_ROOT) is True


@pytest.mark.parametrize("prefix", _FAMILY)
def test_db_routes_through_hexagon_shim(prefix):
    conf = _load(prefix)
    db = conf["servers"]["DB"]
    assert db["deployment"] == "hexagon"
    assert db["fast"] == "sim_db_server"
    assert db["group"] == "action"
    # the GM-5 S3 leg records via the injected RecordingS3Client
    assert db["params"]["s3_record"] is True
    assert db["params"]["aws_bucket"] == "helao-sim"
    modpath = f"helao.deploy.{db['deployment']}.servers.{db['group']}.{db['fast']}"
    mod = import_module(modpath)  # fast_launcher module-path shape
    assert callable(mod.makeApp)
    assert mod.LEGACY_MODULE == "helao.deploy.test.servers.action.sim_db_server"


def test_ws_demo_retired():
    """D5: ws_demo.yml referenced a nonexistent `bokeh: sim_visualizer`
    module (only self-reference in the repo) — it must stay deleted."""
    assert not os.path.exists(os.path.join(_CFG_DIR, "ws_demo.yml"))
