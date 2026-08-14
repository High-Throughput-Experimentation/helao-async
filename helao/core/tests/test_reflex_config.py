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
    from helao.ui.shared.discovery import reserved_addresses

    assert reserved_addresses(
        {"host": "127.0.0.1", "port": 5010, "reflex": "helao_ui"}
    ) == ["127.0.0.1:5010", "127.0.0.1:5011"]


def test_reserved_addresses_claims_one_port_for_bokeh():
    from helao.ui.shared.discovery import reserved_addresses

    assert reserved_addresses(
        {"host": "127.0.0.1", "port": 5002, "bokeh": "live_visualizer"}
    ) == ["127.0.0.1:5002"]


def test_discovery_search_order_puts_configured_deployment_first():
    from helao.helpers import config_loader
    from helao.ui.shared.discovery import deployment_search_order

    saved = config_loader.CONFIG
    try:
        config_loader.CONFIG = {"deployment": "test"}
        order = deployment_search_order()
        assert order[0] == "test"
        assert "hte" in order
    finally:
        config_loader.CONFIG = saved


def test_vis_subscriber_reuses_the_shared_search_order():
    from helao.ui.bokeh import vis_subscriber
    from helao.ui.shared import discovery

    assert vis_subscriber._deployment_search_order is discovery.deployment_search_order


def test_resolve_panel_module_raises_a_clear_error_for_an_unknown_module():
    from helao.ui.shared.discovery import resolve_panel_module

    with pytest.raises(ModuleNotFoundError) as exc:
        resolve_panel_module("no_such_panel_module")
    assert "no_such_panel_module" in str(exc.value)


def _vis_cfg():
    return {
        "servers": {
            "SIM": {
                "host": "127.0.0.1",
                "port": 8002,
                "group": "action",
                "live_vis": "wssim_panel",
            },
            "OER": {
                "host": "127.0.0.1",
                "port": 8003,
                "group": "action",
                "action_vis": "oersim_panel",
            },
            "UI": {
                "host": "127.0.0.1",
                "port": 5010,
                "group": "visualizer",
                "reflex": "helao_ui",
                "params": {"pages": ["live", "action"]},
            },
        }
    }


def test_panel_targets_finds_both_vis_kinds():
    from helao.ui.reflex.app import panel_targets

    targets = panel_targets(_vis_cfg())
    assert {(t.server_key, t.module_name, t.ws_path) for t in targets} == {
        ("SIM", "wssim_panel", "ws_live"),
        ("OER", "oersim_panel", "ws_data"),
    }


def test_panel_targets_expands_a_list_of_modules():
    cfg = {
        "servers": {
            "SIM": {
                "host": "h",
                "port": 1,
                "live_vis": ["wssim_panel", "gpsim_panel"],
            }
        }
    }
    from helao.ui.reflex.app import panel_targets

    assert len(panel_targets(cfg)) == 2


def test_panel_targets_honors_limit_vis():
    from helao.ui.reflex.app import panel_targets

    targets = panel_targets(_vis_cfg(), limit_vis=["SIM"])
    assert [t.server_key for t in targets] == ["SIM"]


def test_route_map_splits_live_and_action():
    from helao.ui.reflex.app import route_map

    routes = route_map(_vis_cfg(), ["live", "action"])
    assert [t.server_key for t in routes["/live"]] == ["SIM"]
    assert [t.server_key for t in routes["/action"]] == ["OER"]


def test_route_map_always_includes_the_shell_routes():
    from helao.ui.reflex.app import route_map

    routes = route_map(_vis_cfg(), ["live"])
    for path in ("/", "/live", "/operator", "/browser"):
        assert path in routes


def test_route_map_omits_a_page_not_requested_but_keeps_it_reachable_as_empty():
    from helao.ui.reflex.app import route_map

    routes = route_map(_vis_cfg(), ["live"])
    assert routes["/action"] == []


# --- build_app end-to-end -----------------------------------------------
#
# The helper tests above are pure. These construct the real app, because every
# robustness defect this task shipped -- an uncaught panel import error, an
# AttributeError on a malformed params block, a bare-string `pages` silently
# erasing every route -- lived in build_app and none of them were reachable
# from panel_targets/route_map alone.


def _ui_cfg(params):
    return {
        "servers": {
            "SIM": {
                "host": "127.0.0.1",
                "port": 8002,
                "group": "action",
                "live_vis": "wssim_panel",
            },
            "UI": {
                "host": "127.0.0.1",
                "port": 5010,
                "group": "visualizer",
                "reflex": "helao_ui",
                "params": params,
            },
        }
    }


def test_build_app_survives_a_params_block_that_is_not_a_mapping():
    """build_app runs at import time; an AttributeError here kills the module."""
    from helao.ui.reflex.app import build_app

    assert build_app(_ui_cfg(["live"]), "UI") is not None


def test_build_app_survives_a_missing_server_entry():
    from helao.ui.reflex.app import build_app

    assert build_app({"servers": {}}, "NOPE") is not None


def test_a_bare_string_pages_value_still_selects_that_page():
    """`pages: live` is an easy YAML slip; set("live") would erase every route."""
    from helao.ui.reflex.app import route_map

    routes = route_map(_ui_cfg({"pages": "live"}), "live")
    assert [t.server_key for t in routes["/live"]] == ["SIM"]


def test_a_bare_string_limit_vis_filters_by_whole_key_not_substring():
    from helao.ui.reflex.app import panel_targets

    cfg = _ui_cfg({})
    assert [t.server_key for t in panel_targets(cfg, limit_vis="SIM")] == ["SIM"]
    assert panel_targets(cfg, limit_vis="S") == []


def test_a_panel_module_that_fails_to_import_renders_an_error_card(monkeypatch):
    """Isolation is the point: one bad panel must not take down the page.

    Task 7 writes real panel modules against exactly this guarantee, and an
    import-time NameError is not a ModuleNotFoundError.
    """
    from helao.ui.reflex import app as app_mod

    def _boom(_name):
        raise NameError("typo at module scope")

    monkeypatch.setattr(app_mod, "resolve_panel_module", _boom)
    card = app_mod._render_panel(
        app_mod.PanelTarget("SIM", "wssim_panel", "ws_live", "live_vis")
    )
    assert card is not None


def test_an_unknown_panel_module_renders_an_error_card():
    from helao.ui.reflex.app import PanelTarget, _render_panel

    card = _render_panel(PanelTarget("SIM", "no_such_panel", "ws_live", "live_vis"))
    assert card is not None


def test_the_buffer_route_is_reachable_through_the_built_app():
    """Bulk column data rides this route, not Reflex state. No route, no data."""
    import numpy as np
    from fastapi.testclient import TestClient
    from starlette.applications import Starlette

    from helao.ui.reflex import plots
    from helao.ui.reflex.app import build_app

    app = build_app(_ui_cfg({"pages": ["live"]}), "UI")
    plots.STORE.put("rt", 2, [memoryview(np.arange(3, dtype=np.float64).tobytes())])
    # `api_transformer` is typed as a broader union (a single transformer, a
    # sequence of them, or None) than `TestClient` accepts; narrow it to the
    # single Starlette/FastAPI app `build_app` actually installs.
    assert isinstance(app.api_transformer, Starlette)
    client = TestClient(app.api_transformer)
    assert client.get("/xy/buffers/rt?v=2").status_code == 200
    assert client.get("/xy/buffers/rt?v=1").status_code == 404
    assert client.get("/xy/buffers/ghost?v=1").status_code == 404


def test_ingest_lifespan_is_an_async_context_manager_so_teardown_is_awaited():
    """A plain coroutine is only cancelled; the drain loops would outlive the app.

    Every ``rx.App`` registers other lifespan tasks by default -- notably
    ``App._setup_event_processor``, which is itself wrapped in
    ``contextlib.asynccontextmanager`` -- so asserting that *any* registered
    task has that shape would pass even if the ingest task were still a plain
    coroutine. This isolates the ingest task by name (``__name__`` survives
    ``functools.wraps`` through the decorator) before checking its shape, so a
    regression back to a plain coroutine actually fails this test.
    """
    import contextlib
    import inspect

    from helao.ui.reflex.app import build_app

    app = build_app(_ui_cfg({"pages": ["live"]}), "UI")
    tasks = list(getattr(app, "lifespan_tasks", []) or [])
    ingest_tasks = [
        task for task in tasks if getattr(task, "__name__", "") == "_ingest_lifespan"
    ]
    assert ingest_tasks, "no _ingest_lifespan task registered"
    task = ingest_tasks[0]
    assert isinstance(
        task, contextlib._AsyncGeneratorContextManager
    ) or inspect.isasyncgenfunction(getattr(task, "__wrapped__", task))


def test_deployment_search_order_finds_every_deployment():
    """The scan was silently finding none.

    discovery.py sits one directory deeper than the vis_subscriber it was lifted
    from, so the copied dirname-counting resolved to helao/core/deploy, which
    does not exist. Only the configured deployment (or hte) was ever searched,
    and every Reflex panel resolved to "module not found" at runtime.
    """
    from helao.helpers import config_loader
    from helao.ui.shared.discovery import deployment_search_order

    saved = config_loader.CONFIG
    try:
        config_loader.CONFIG = {"deployment": "test"}
        order = deployment_search_order()
        assert order[0] == "test"
        assert "hte" in order
        assert len(order) > 2, f"fallback scan found nothing: {order}"
    finally:
        config_loader.CONFIG = saved


def test_ui_only_servers_are_excluded_from_orchestrator_polling():
    """An orchestrator dispatching at a UI server yields a stream of 405s.

    reflex was added after bokeh/demovis and missed at all three call sites,
    which is why this predicate is shared rather than inlined.
    """
    from helao.helpers.config_loader import is_ui_only_server

    assert is_ui_only_server({"reflex": "helao_ui"})
    assert is_ui_only_server({"bokeh": "live_visualizer"})
    assert is_ui_only_server({"demovis": "x"})
    assert not is_ui_only_server({"fast": "ws_simulator"})
    assert not is_ui_only_server({})
    assert not is_ui_only_server(None)


def test_no_caller_still_inlines_the_ui_server_skip_list():
    """Guards the next UI kind against being missed the way reflex was."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for path in (root / "helao" / "core").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r'"bokeh"\s+not\s+in\s+\w+\s+and\s+"demovis"', text):
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"inlined UI skip list: {offenders}"


def test_the_backend_child_process_resolves_its_panels():
    """The failure the browser surfaced: every panel showed "module not found".

    The backend is a child process that loads the config itself, so it must also
    set CONFIG["deployment"] -- bokeh_launcher does this in its own process.
    Without it the config's own deployment is never searched.
    """
    import os
    import subprocess
    import sys

    root = os.getcwd()
    env = dict(os.environ)
    env["PYTHONPATH"] = root
    env["HELAO_REFLEX_CONFIG"] = "goldenreflex"
    env["HELAO_REFLEX_SERVER_KEY"] = "UI"
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "from helao.ui.reflex.app import app\n"
            "from helao.ui.shared.discovery import resolve_panel_module\n"
            "resolve_panel_module('wssim_panel')\n"
            "resolve_panel_module('oersim_panel')\n"
            "print('RESOLVED')",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=root,
        timeout=180,
    )
    assert (
        "RESOLVED" in proc.stdout
    ), f"panels unresolvable in the backend child:\n{proc.stdout}\n{proc.stderr}"


def test_only_plots_module_imports_xy():
    """Only the facade and the binding may touch the alpha xy API."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for path in root.rglob("*.py"):
        # `.claude/worktrees/` holds checkouts of other branches. Sweeping them
        # judges this branch by another's code -- and reports a violation whose
        # file the reader cannot find at the path given. run_tests.py skips the
        # same directory for the same reason.
        parts = path.parts
        if "/.git/" in str(path) or "site-packages" in str(path) or ".claude" in parts:
            continue
        if path.name in (
            "plots.py",
            "xy_component.py",
            "test_reflex_plots.py",
            "test_reflex_xy_component.py",
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if re.search(r"^\s*(import xy\b|from xy\b)", text, re.MULTILINE):
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"xy imported outside facade/binding: {offenders}"


def test_a_panel_module_may_declare_a_socket_the_config_key_does_not_imply():
    """`live_vis` normally means ws_live, but a panel is free to read ws_data
    while still belonging on the live page -- one real deployment has a
    potentiostat panel shaped exactly that way. Deriving the socket from the
    key alone subscribes to the wrong one, and the panel then reports no
    ingest for a path nothing is feeding."""
    from helao.ui.reflex.app import panel_targets

    # nidaqmx_vis declares WS_PATH = "ws_data" but is placed under live_vis
    # here, which is the shape that matters.
    cfg = {
        "servers": {
            "PSTAT": {
                "host": "h",
                "port": 1,
                "group": "action",
                "live_vis": "nidaqmx_vis",
            }
        }
    }
    target = panel_targets(cfg)[0]
    assert target.ws_path == "ws_data", "the module's own WS_PATH must win"
    # The key still decides which page the panel appears on.
    assert target.vis_key == "live_vis"


def test_an_unresolvable_panel_module_keeps_the_key_derived_socket():
    """Discovery must not break on a module that cannot be imported --
    _render_panel already renders that case as an error card."""
    from helao.ui.reflex.app import panel_targets

    cfg = {
        "servers": {
            "X": {
                "host": "h",
                "port": 1,
                "group": "action",
                "action_vis": "no_such_panel",
            }
        }
    }
    target = panel_targets(cfg)[0]
    assert target.ws_path == "ws_data"
