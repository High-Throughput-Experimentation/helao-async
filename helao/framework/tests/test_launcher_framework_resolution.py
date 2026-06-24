"""Launcher framework-path resolution + config-global bridge."""
import importlib


def test_fast_resolver_framework_vs_deploy():
    fl = importlib.import_module("fast_launcher")
    assert fl.resolve_app_module_path("framework", "orchestrator", "orchestrator") == \
        "helao.framework.app.servers.orchestrator"
    assert fl.resolve_app_module_path("hte", "orchestrator", "async_orch2") == \
        "helao.deploy.hte.servers.orchestrator.async_orch2"


def test_bokeh_resolver_framework_vs_deploy():
    bl = importlib.import_module("bokeh_launcher")
    assert bl.resolve_app_module_path("framework", "operator", "standalone_operator") == \
        "helao.framework.app.servers.standalone_operator"
    assert bl.resolve_app_module_path("test", "visualizer", "oersim_vis") == \
        "helao.deploy.test.servers.visualizer.oersim_vis"


def test_config_bridge_helper():
    """bridge_framework_config points the framework global at the legacy CONFIG object."""
    fl = importlib.import_module("fast_launcher")
    from helao.helpers import config_loader as legacy
    from helao.framework.support import config_loader as fw
    prev_legacy, prev_fw = legacy.CONFIG, fw.CONFIG
    try:
        legacy.CONFIG = {"sentinel": 1}
        fl.bridge_framework_config()
        assert fw.CONFIG is legacy.CONFIG
    finally:
        legacy.CONFIG, fw.CONFIG = prev_legacy, prev_fw
