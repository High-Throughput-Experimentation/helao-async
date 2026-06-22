"""Tests for helao.framework.support.config_loader.

Ports the assertions from the legacy config_loader unit test, but against
tmp config files (never real deploy configs). Also asserts that importing
the module performs NO file read (the module-level CONFIG stays None).
"""
import subprocess
import sys
import tempfile

import pytest

from helao.framework.support import config_loader
from helao.framework.support.config_loader import (
    HelaoConfig,
    OrchServerParams,
    ServerConfig,
    read_config,
    load_global_config,
)

_DEMO_YML = """\
run_type: simulation
root: /tmp/INST_hlo
dummy: true
simulation: true
servers:
  ORCH:
    host: 127.0.0.1
    port: 8001
    group: orchestrator
    fast: async_orch2
  MOTOR:
    host: 127.0.0.1
    port: 8002
    group: action
    fast: galil_motion
"""

_DEMO_PY = """\
config = {
    "run_type": "simulation",
    "root": "/tmp/INST_hlo",
    "servers": {
        "ORCH": {
            "host": "127.0.0.1",
            "port": 8001,
            "group": "orchestrator",
        },
    },
}
"""


def test_import_is_side_effect_free():
    assert config_loader.CONFIG is None


def test_import_does_not_read_config_file():
    # Importing the module in a clean subprocess must not raise / read disk.
    code = (
        "from helao.framework.support import config_loader as c; "
        "assert c.CONFIG is None; print('ok')"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr
    assert "ok" in out.stdout


def test_read_config_explicit_yml(tmp_path):
    p = tmp_path / "demo0.yml"
    p.write_text(_DEMO_YML)
    config = read_config(str(p))
    assert isinstance(config, dict)
    assert isinstance(config["servers"], dict)
    assert config["loaded_config_path"] == str(p.resolve())
    import os

    assert os.path.isdir(config["helao_repo_root"])
    assert "helao_credentials_path" in config


def test_read_config_explicit_py(tmp_path):
    p = tmp_path / "demo_py.py"
    p.write_text(_DEMO_PY)
    config = read_config(str(p))
    assert config["run_type"] == "simulation"
    assert config["servers"]["ORCH"]["group"] == "orchestrator"


def test_helao_config_parses_yml(tmp_path):
    p = tmp_path / "demo0.yml"
    p.write_text(_DEMO_YML)
    config = read_config(str(p))
    parsed = HelaoConfig(**config)
    assert parsed.run_type == "simulation"
    assert all(isinstance(v, ServerConfig) for v in parsed.servers.values())
    assert parsed.servers["ORCH"].group == "orchestrator"


def test_missing_explicit_yml_raises():
    with pytest.raises(FileNotFoundError):
        read_config("/this/path/does/not/exist/__nope__.yml")


def test_unknown_prefix_raises():
    with pytest.raises(FileNotFoundError):
        read_config("__definitely_not_a_real_prefix__")


def test_helao_config_minimal_defaults():
    minimal = HelaoConfig(run_type="rt", root=tempfile.gettempdir())
    assert minimal.dummy is True
    assert minimal.simulation is True


def test_orch_server_params_defaults():
    p = OrchServerParams()
    assert p.heartbeat_interval == 10.0
    assert p.verify_plates is True


def test_load_global_config_no_set_keeps_none(tmp_path):
    p = tmp_path / "demo0.yml"
    p.write_text(_DEMO_YML)
    result = load_global_config(str(p), set_global=False)
    assert isinstance(result, dict)
    assert config_loader.CONFIG is None


def test_load_global_config_set_global(tmp_path):
    p = tmp_path / "demo0.yml"
    p.write_text(_DEMO_YML)
    try:
        load_global_config(str(p), set_global=True)
        assert config_loader.CONFIG is not None
        assert config_loader.CONFIG.run_type == "simulation"
    finally:
        config_loader.CONFIG = None
