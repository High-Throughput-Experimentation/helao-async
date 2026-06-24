# helao/framework/tests/test_app_servers_operator.py
"""Framework generic standalone operator host app."""
import pytest

from helao.framework.support import config_loader


class FakeDoc:
    def __init__(self):
        self.title = None
        self.roots = []
        self.operator = None

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
        # no experiment_libraries / sequence_libraries → RemoteBackend autoload is empty
        "servers": {
            "OP": {"host": "127.0.0.1", "port": 5003, "params": {"poll_interval": 1.0}},
            "ORCH": {"group": "orchestrator", "host": "127.0.0.1", "port": 8001},
        },
    }
    yield config_loader.CONFIG
    config_loader.CONFIG = prev_cfg
    helao_logging.LOGGER = prev_log


def test_operator_app_builds_and_binds_backend(cfg, monkeypatch):
    import helao.framework.adapters.operator_backend as _ob_mod
    from helao.framework.app.servers.standalone_operator import makeBokehApp
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    from helao.framework.adapters.operator_backend import RemoteBackend

    # import_autolibs uses a module-level CONFIG from helao.helpers.config_loader
    # (bound at import time, always None in the test process).  Stub it out so
    # RemoteBackend.__init__ returns empty libs without touching the filesystem.
    monkeypatch.setattr(
        _ob_mod, "import_autolibs", lambda **kw: ({}, {}, {})
    )
    # RemoteBackend.subscribe creates asyncio tasks (WsSubscriber + poll loop)
    # which require a running event loop.  Stub it to a no-op; this test only
    # asserts wiring (orch_key), not live orchestrator communication.
    monkeypatch.setattr(_ob_mod.RemoteBackend, "subscribe", lambda self, cb: None)

    doc = FakeDoc()
    out = makeBokehApp(doc, "demo", "OP", "/repo")
    assert out is doc
    assert isinstance(doc.operator, BokehOperator)
    assert isinstance(doc.operator.backend, RemoteBackend)
    # backend resolved the lone group:orchestrator server
    assert doc.operator.backend.orch_key == "ORCH"
