# helao/framework/tests/test_app_servers_visualizers.py
"""Framework generic visualizer host apps (action/live)."""
import pytest

from helao.framework.support import config_loader
from helao.framework.adapters import vis_subscriber as vsmod


class FakeDoc:
    def __init__(self):
        self.title = None
        self.roots = []

    def add_root(self, root):
        self.roots.append(root)

    def add_next_tick_callback(self, cb):
        pass

    def on_session_destroyed(self, cb):
        pass


@pytest.fixture
def cfg(tmp_path):
    prev_cfg = config_loader.CONFIG
    from helao.framework.support import helao_logging
    prev_log = helao_logging.LOGGER
    config_loader.CONFIG = {
        "root": str(tmp_path / "INST"),
        "loaded_config_path": "/configs/demo.yml",
        "servers": {
            "VIS": {"host": "127.0.0.1", "port": 5001, "params": {}},
            "ACT": {"host": "127.0.0.1", "port": 5002},
        },
    }
    yield config_loader.CONFIG
    config_loader.CONFIG = prev_cfg
    helao_logging.LOGGER = prev_log


def test_action_visualizer_mounts_header(cfg):
    from helao.framework.app.servers.action_visualizer import makeBokehApp
    doc = FakeDoc()
    out = makeBokehApp(doc, "demo", "VIS", "/repo")
    assert out is doc
    assert len(doc.roots) >= 1  # header banner mounted


def test_live_visualizer_mounts_header(cfg):
    from helao.framework.app.servers.live_visualizer import makeBokehApp
    doc = FakeDoc()
    out = makeBokehApp(doc, "demo", "VIS", "/repo")
    assert out is doc
    assert len(doc.roots) >= 1


def test_action_visualizer_mounts_declared_vis(cfg, monkeypatch):
    """A server declaring action_vis gets its C_vis instantiated via mount_visualizers."""
    from helao.framework.app.servers.action_visualizer import makeBokehApp
    cfg["servers"]["ACT"]["action_vis"] = "x_vis"
    made = []

    class FakeC:
        def __init__(self, vis_serv, serv_key):
            made.append(serv_key)

    monkeypatch.setattr(vsmod, "import_vis_class", lambda name: FakeC)
    makeBokehApp(FakeDoc(), "demo", "VIS", "/repo")
    assert made == ["ACT"]
