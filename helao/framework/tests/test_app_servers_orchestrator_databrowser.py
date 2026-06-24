# helao/framework/tests/test_app_servers_orchestrator_databrowser.py
"""Framework orchestrator + data_browser generic entries."""
import pytest

from helao.framework.support import config_loader


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
    prev = config_loader.CONFIG
    from helao.framework.support import helao_logging
    prev_log = helao_logging.LOGGER
    config_loader.CONFIG = {
        "root": str(tmp_path / "INST"),
        "loaded_config_path": "/configs/demo.yml",
        "servers": {
            "ORCH": {"group": "orchestrator", "host": "127.0.0.1", "port": 8001},
            "MOTOR": {"group": "action", "host": "127.0.0.1", "port": 8002},
            "VIS": {"group": "visualizer", "host": "127.0.0.1", "port": 5003, "params": {}},
        },
    }
    yield config_loader.CONFIG
    config_loader.CONFIG = prev
    helao_logging.LOGGER = prev_log


def test_orchestrator_entry_builds_app(cfg):
    from helao.framework.app.servers.orchestrator import makeApp
    app = makeApp("ORCH")
    assert app is not None
    assert hasattr(app.state, "driver")
    # action_servers derived from CONFIG (pingable action servers present)
    assert "MOTOR" in app.state.driver.action_servers


def test_data_browser_entry_builds_doc(cfg):
    from helao.framework.app.servers.data_browser import makeBokehApp
    doc = FakeDoc()
    out = makeBokehApp(doc, "demo", "VIS", "/repo")
    assert out is doc
    assert len(doc.roots) >= 1
