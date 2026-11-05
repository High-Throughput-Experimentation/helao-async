"""resolve_app_deployment: launcher semantics kept, any servers/* folder accepted."""

import logging
from pathlib import Path

import pytest

from helao.helpers import launcher_bootstrap as lb


def _touch(root: Path, rel: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("", encoding="utf-8")
    return p


LOG = logging.getLogger("t")


def test_new_layout_module_is_found(tmp_path):
    _touch(tmp_path, "alpha/servers/gamry/gamry_server2.py")
    cfg = _touch(tmp_path, "alpha/configs/c.yml")
    entry = {"group": "action", "fast": "gamry_server2"}
    assert lb.resolve_app_deployment(entry, "gamry_server2", str(cfg), LOG) == "alpha"


def test_explicit_key_is_returned_unchecked(tmp_path):
    cfg = _touch(tmp_path, "alpha/configs/c.yml")
    entry = {"group": "action", "fast": "x", "deployment": "beta"}
    assert lb.resolve_app_deployment(entry, "x", str(cfg), LOG) == "beta"


def test_ambiguous_foreign_module_warns_and_takes_first(tmp_path, caplog):
    _touch(tmp_path, "beta/servers/action/x.py")
    _touch(tmp_path, "gamma/servers/action/x.py")
    _touch(tmp_path, "alpha/servers/action/other.py")
    cfg = _touch(tmp_path, "alpha/configs/c.yml")
    with caplog.at_level(logging.WARNING):
        dep = lb.resolve_app_deployment({"group": "action"}, "x", str(cfg), LOG)
    assert dep == "beta"
    assert "deployment:" in caplog.text


def test_unknown_module_raises(tmp_path):
    _touch(tmp_path, "alpha/servers/action/other.py")
    cfg = _touch(tmp_path, "alpha/configs/c.yml")
    with pytest.raises(FileNotFoundError):
        lb.resolve_app_deployment({"group": "action"}, "nope", str(cfg), LOG)


def test_app_module_path_for_real_hte_server():
    assert lb.app_module_path("hte", "gamry_server2").endswith(".gamry_server2")


def test_app_module_path_missing_raises():
    with pytest.raises(FileNotFoundError, match="no_such_module"):
        lb.app_module_path("hte", "no_such_module")
