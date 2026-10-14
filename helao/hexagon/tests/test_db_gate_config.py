"""P2e gate-config checks (D3): every goldenhex-family config names the native
DB module directly (no routing key), the dotted path import-resolves (same
shape fast_launcher builds), and the config still validates. Mirrors
test_vis_gate_config.py."""

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
def test_db_is_native_and_keeps_the_s3_leg(prefix):
    """``sim_db_server`` builds an ``ActionHost`` directly, so SYNC carries NO
    ``deployment`` routing key.

    The S3 params stay asserted here: they are the GM-5 leg's contract, and
    they are config, not code.
    """
    conf = _load(prefix)
    db = conf["servers"]["SYNC"]
    assert "deployment" not in db
    assert db["fast"] == "sim_db_server"
    assert db["group"] == "action"
    # the GM-5 S3 leg records via the injected RecordingS3Client
    assert db["params"]["s3_record"] is True
    assert db["params"]["aws_bucket"] == "helao-sim"
    # fast_launcher's module-path shape for a server with no deployment key
    mod = import_module(f"helao.deploy.test.servers.action.{db['fast']}")
    assert callable(mod.makeApp)


def test_ws_demo_retired():
    """D5: ws_demo.yml referenced a nonexistent `bokeh: sim_visualizer`
    module (only self-reference in the repo) — it must stay deleted."""
    assert not os.path.exists(os.path.join(_CFG_DIR, "ws_demo.yml"))
