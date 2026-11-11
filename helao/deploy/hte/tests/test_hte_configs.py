"""hte's config and env-resolution checks (moved from parent tests)."""

from pathlib import Path

import pytest

import helao_env as he
from helao.helpers.config_loader import HelaoConfig, ServerConfig, read_config
from helao.helpers.launcher_bootstrap import app_module_path

CONFIGS = sorted((Path(__file__).resolve().parents[1] / "configs").glob("*.yml"))


def test_hte_has_tracked_configs():
    assert CONFIGS


@pytest.mark.parametrize("path", CONFIGS, ids=[p.stem for p in CONFIGS])
def test_every_hte_config_validates(path):
    parsed = HelaoConfig.model_validate(read_config(str(path)))
    assert all(isinstance(v, ServerConfig) for v in (parsed.servers or {}).values())


def test_server_folders_of_a_real_hte_config():
    folders = {f.name for f in he.server_folders(he.resolve_config("hte/anec"))}
    assert {"gamry", "nidaqmx", "galil_motion"} <= folders


def test_app_module_path_for_real_hte_server():
    assert app_module_path("hte", "gamry_server2").endswith(".gamry_server2")
