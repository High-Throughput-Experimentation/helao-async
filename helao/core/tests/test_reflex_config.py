"""Tests for `reflex:` config validation and shared module discovery."""

import pytest

from helao.helpers.config_loader import ServerConfig


def _pidd():
    """Return a stand-in carrying only the attributes validateConfig reads."""

    class _P:
        reqKeys = ("host", "port", "group")
        codeKeys = ("fast", "bokeh", "reflex")

    return _P()


def test_serverconfig_accepts_a_reflex_key():
    cfg = ServerConfig(
        host="127.0.0.1", port=5010, group="visualizer", reflex="helao_ui"
    )
    assert cfg.reflex == "helao_ui"
    assert cfg.fast is None and cfg.bokeh is None


def test_serverconfig_reflex_defaults_to_none():
    assert ServerConfig(host="h", port=1, group="action").reflex is None


def test_pidd_codekeys_include_reflex():
    import inspect

    from launch import Pidd

    src = inspect.getsource(Pidd.__init__)
    assert '"reflex"' in src or "'reflex'" in src


def test_validate_rejects_two_code_keys_including_reflex():
    from launch import validateConfig

    conf = {
        "servers": {
            "UI": {
                "host": "127.0.0.1",
                "port": 5010,
                "group": "visualizer",
                "reflex": "helao_ui",
                "bokeh": "live_visualizer",
            }
        }
    }
    assert validateConfig(_pidd(), conf, ".") is False


def test_validate_accepts_a_reflex_only_server():
    from launch import validateConfig

    conf = {
        "servers": {
            "UI": {
                "host": "127.0.0.1",
                "port": 5010,
                "group": "visualizer",
                "reflex": "helao_ui",
            }
        }
    }
    assert validateConfig(_pidd(), conf, ".") is True


def test_validate_rejects_a_server_colliding_with_the_reflex_backend_port():
    from launch import validateConfig

    conf = {
        "servers": {
            "UI": {
                "host": "127.0.0.1",
                "port": 5010,
                "group": "visualizer",
                "reflex": "helao_ui",
            },
            "SIM": {
                "host": "127.0.0.1",
                "port": 5011,
                "group": "action",
                "fast": "ws_simulator",
            },
        }
    }
    assert validateConfig(_pidd(), conf, ".") is False


def test_reserved_addresses_claims_two_ports_for_reflex():
    from helao.core.servers.reflex.discovery import reserved_addresses

    assert reserved_addresses(
        {"host": "127.0.0.1", "port": 5010, "reflex": "helao_ui"}
    ) == ["127.0.0.1:5010", "127.0.0.1:5011"]


def test_reserved_addresses_claims_one_port_for_bokeh():
    from helao.core.servers.reflex.discovery import reserved_addresses

    assert reserved_addresses(
        {"host": "127.0.0.1", "port": 5002, "bokeh": "live_visualizer"}
    ) == ["127.0.0.1:5002"]


def test_discovery_search_order_puts_configured_deployment_first():
    from helao.helpers import config_loader
    from helao.core.servers.reflex.discovery import deployment_search_order

    saved = config_loader.CONFIG
    try:
        config_loader.CONFIG = {"deployment": "test"}
        order = deployment_search_order()
        assert order[0] == "test"
        assert "hte" in order
    finally:
        config_loader.CONFIG = saved


def test_vis_subscriber_reuses_the_shared_search_order():
    from helao.core.servers import vis_subscriber
    from helao.core.servers.reflex import discovery

    assert vis_subscriber._deployment_search_order is discovery.deployment_search_order


def test_resolve_panel_module_raises_a_clear_error_for_an_unknown_module():
    from helao.core.servers.reflex.discovery import resolve_panel_module

    with pytest.raises(ModuleNotFoundError) as exc:
        resolve_panel_module("no_such_panel_module")
    assert "no_such_panel_module" in str(exc.value)
