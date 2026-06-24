"""Unit tests for the framework Bokeh visualizer host (app/vis.py)."""
import pytest

from helao.framework.support import config_loader
from helao.framework.app import vis as vis_mod
from helao.framework.app.vis import HelaoVis, Vis, makeBokehApp


class FakeDoc:
    """Minimal stand-in for a Bokeh Document."""

    def __init__(self):
        self.title = None
        self.roots = []
        self.session_destroyed_cb = None

    def add_root(self, root):
        self.roots.append(root)

    def add_next_tick_callback(self, cb):
        self.next_tick = cb

    def on_session_destroyed(self, cb):
        self.session_destroyed_cb = cb


@pytest.fixture
def cfg(tmp_path):
    """Install a minimal world config on config_loader.CONFIG, restore after."""
    prev = config_loader.CONFIG
    config_loader.CONFIG = {
        "root": str(tmp_path / "INST"),
        "loaded_config_path": "/configs/demo.yml",
        "servers": {
            "VIS": {"host": "127.0.0.1", "port": 5001, "params": {"doc_name": "Demo Vis"}},
        },
    }
    yield config_loader.CONFIG
    config_loader.CONFIG = prev


def test_helaovis_builds(cfg):
    doc = FakeDoc()
    app = HelaoVis(server_key="VIS", doc=doc)
    assert app.helao_srv == "VIS"
    assert app.server_params == {"doc_name": "Demo Vis"}
    assert app.doc_name == "Demo Vis"
    assert doc.title == "Demo Vis"
    assert isinstance(app.vis, Vis)
    assert str(app.vis.helaodirs.root) == cfg["root"]


def test_vis_raises_without_root(tmp_path):
    prev = config_loader.CONFIG
    config_loader.CONFIG = {
        "loaded_config_path": "/configs/noroot.yml",
        "servers": {"VIS": {"host": "h", "port": 1, "params": {}}},
    }
    try:
        with pytest.raises(ValueError):
            HelaoVis(server_key="VIS", doc=FakeDoc())
    finally:
        config_loader.CONFIG = prev


@pytest.mark.skip(reason="depends on Task 3 vis_subscriber.mount_visualizers")
def test_makebokehapp_returns_doc_with_roots(cfg):
    doc = FakeDoc()
    out = makeBokehApp(doc, "demo", "VIS", "/repo/root")
    assert out is doc
    assert len(doc.roots) >= 1  # header banner mounted
