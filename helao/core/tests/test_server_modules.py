"""server_modules: one lookup for app, Bokeh and Reflex modules in every deployment."""

from pathlib import Path

import pytest

from helao.helpers import server_modules as sm


def _touch(root: Path, rel: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("", encoding="utf-8")
    return p


@pytest.fixture
def root(tmp_path):
    _touch(tmp_path, "alpha/servers/action/old_server.py")  # old layout
    _touch(tmp_path, "alpha/servers/gamry/gamry_server2.py")  # new layout
    _touch(tmp_path, "alpha/servers/gamry/bokeh/gamry_vis.py")
    _touch(tmp_path, "alpha/servers/gamry/reflex/gamry_vis.py")
    _touch(tmp_path, "alpha/servers/visualizer/live_visualizer.py")
    _touch(tmp_path, "alpha/servers/reflex/temp_vis.py")
    _touch(tmp_path, "alpha/servers/visualizer/temp_vis.py")
    _touch(tmp_path, "beta/servers/action/shared.py")
    _touch(tmp_path, "gamma/servers/action/shared.py")
    (tmp_path / "noservers").mkdir()
    return tmp_path


def test_deployments_are_dirs_with_servers(root):
    assert sm.deployments(root) == ["alpha", "beta", "gamma"]


@pytest.mark.parametrize(
    "module, stack, rel",
    [
        ("old_server", "app", "alpha/servers/action/old_server.py"),
        ("gamry_server2", "app", "alpha/servers/gamry/gamry_server2.py"),
        ("live_visualizer", "app", "alpha/servers/visualizer/live_visualizer.py"),
        ("gamry_vis", "bokeh", "alpha/servers/gamry/bokeh/gamry_vis.py"),
        ("gamry_vis", "reflex", "alpha/servers/gamry/reflex/gamry_vis.py"),
        ("temp_vis", "bokeh", "alpha/servers/visualizer/temp_vis.py"),
        ("temp_vis", "reflex", "alpha/servers/reflex/temp_vis.py"),
    ],
)
def test_each_stack_finds_its_own_file(root, module, stack, rel):
    assert sm.module_file("alpha", module, stack, root) == root / rel


def test_app_stack_never_returns_a_reflex_panel(root):
    # servers/reflex/temp_vis.py is servers/*/temp_vis.py, but it is a panel
    assert sm.module_file("alpha", "temp_vis", "app", root) == (
        root / "alpha/servers/visualizer/temp_vis.py"
    )


def test_twins_in_one_deployment_are_an_error(root):
    _touch(root, "alpha/servers/other/gamry_server2.py")
    with pytest.raises(sm.AmbiguousModule, match="gamry_server2"):
        sm.module_file("alpha", "gamry_server2", "app", root)


def test_missing_module_is_none(root):
    assert sm.module_file("alpha", "nope", "app", root) is None


def test_unknown_stack_raises(root):
    with pytest.raises(ValueError):
        sm.module_file("alpha", "x", "wrong", root)


def test_locate_prefers_own_then_unique(root):
    assert sm.locate("shared", "app", own="gamma", deploy_root=root) == (
        "gamma",
        ["beta", "gamma"],
    )
    assert sm.locate("old_server", "app", own="beta", deploy_root=root) == (
        "alpha",
        ["alpha"],
    )


def test_locate_reports_ambiguity_without_choosing(root):
    assert sm.locate("shared", "app", own="alpha", deploy_root=root) == (
        None,
        ["beta", "gamma"],
    )


def test_import_path_is_dotted_from_helao(root):
    f = root / "alpha/servers/gamry/bokeh/gamry_vis.py"
    assert sm.import_path(f, root) == "helao.deploy.alpha.servers.gamry.bokeh.gamry_vis"


def test_real_deploy_root_holds_base_and_test():
    assert {"base", "test"} <= set(sm.deployments())
