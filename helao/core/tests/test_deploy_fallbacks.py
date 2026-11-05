"""No deployment is preferred by name; a shared name is an error, not a pick."""

from pathlib import Path

import pytest

from helao.core.drivers.data import analysis_driver
from helao.core.hooks import loader
from helao.helpers import config_loader, server_modules


def _touch(root: Path, rel: str, text: str = "") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def tree(tmp_path, monkeypatch):
    for dep in ("a", "b", "c"):
        _touch(tmp_path, f"{dep}/servers/action/x.py")
    _touch(tmp_path, "a/processors/mine.py")
    _touch(tmp_path, "b/processors/shared.py")
    _touch(tmp_path, "c/processors/shared.py")
    _touch(tmp_path, "b/processors/only_b.py")
    _touch(tmp_path, "a/processors/both.py")
    _touch(tmp_path, "b/processors/both.py")
    monkeypatch.setattr(server_modules, "DEPLOY_ROOT", tmp_path)
    monkeypatch.setattr(config_loader, "CONFIG", {"deployment": "a"})
    monkeypatch.chdir(tmp_path.parent)  # cwd must not matter
    return tmp_path


def test_own_processor(tree):
    assert loader._resolve_path("mine") == str(tree / "a/processors/mine.py")


def test_own_processor_wins_over_another_deployments(tree):
    assert loader._resolve_path("both") == str(tree / "a/processors/both.py")


def test_unique_foreign_processor(tree):
    assert loader._resolve_path("only_b") == str(tree / "b/processors/only_b.py")


def test_shared_foreign_processor_is_an_error(tree):
    with pytest.raises(loader.HookConfigError, match="shared"):
        loader._resolve_path("shared")


def test_analyses_new_location_preferred():
    assert analysis_driver.ANALYSES_SUBPKGS[0] == "servers.analysis.analyses"
    assert "drivers.data.analyses" in analysis_driver.ANALYSES_SUBPKGS
