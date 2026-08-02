# helao/core/tests/test_reflex_routes_e2e.py
"""End-to-end checks that the Reflex app builds every route from a real config.

This builds the app in-process rather than launching it: a full launch needs an
exported frontend bundle, which is a developer-machine artifact. Browser-level
verification is the manual step in the plan.
"""

import pytest

from helao.helpers import config_loader


@pytest.fixture
def reflex_cfg():
    """Load goldenreflex.yml and install it as the global config."""
    saved = config_loader.CONFIG
    cfg, _ = config_loader.read_validated_config("goldenreflex")
    config_loader.install_global_config(cfg)
    yield config_loader.CONFIG
    config_loader.CONFIG = saved


def test_goldenreflex_config_is_valid(reflex_cfg):
    from launch import validateConfig

    class _P:
        reqKeys = ("host", "port", "group")
        codeKeys = ("fast", "bokeh", "reflex")

    assert validateConfig(_P(), reflex_cfg, ".") is True


def test_goldenreflex_keeps_the_bokeh_operator_alongside_reflex(reflex_cfg):
    servers = reflex_cfg["servers"]
    assert servers["OPERATOR"]["bokeh"] == "standalone_operator"
    assert servers["UI"]["reflex"] == "helao_ui"


def test_app_builds_and_registers_every_shell_route(reflex_cfg):
    from helao.core.servers.reflex.app import SHELL_ROUTES, build_app

    application = build_app(reflex_cfg, "UI")
    # Reflex 0.9.7 exposes registered-but-not-yet-compiled routes only via the
    # private `_unevaluated_pages` dict (keyed by route, "/" normalized to
    # "index"); `_pages` stays empty until `_compile()` runs. See the Task 0
    # API note.
    registered = set(application._unevaluated_pages or application._pages)
    for path in SHELL_ROUTES:
        normalized = path if path != "/" else "index"
        assert any(
            normalized.strip("/") in str(r).strip("/") for r in registered
        ), f"route {path} not registered; registered={registered}"


def test_build_app_registers_panel_handlers_without_compiling_pages(reflex_cfg):
    """The freeze this guards, seen in a live browser: every panel stuck at
    "connecting", with the backend logging

        KeyError: No registered handler found for event:
        ...wssim_panel_sim__state.render_loop

    ``add_page`` takes a lazy callable, and ``reflex run --backend-only`` never
    compiles pages -- so panel state classes built inside that callable were
    never created in the serving process, and Reflex registers a state's event
    handlers at class creation. The frontend bundle, built by a separate
    ``reflex export`` that *did* compile, then called handlers the backend had
    never heard of.

    This test deliberately does not compile: that is the condition under test.
    """
    from reflex_base.registry import RegistrationContext

    from helao.core.servers.reflex.app import build_app

    build_app(reflex_cfg, "UI")
    registered = set(RegistrationContext.get().event_handlers)
    for panel, server in (
        ("wssim_panel", "sim"),
        ("oersim_panel", "cpsim"),
        ("gpsim_panel", "gpsim"),
    ):
        for handler in ("render_loop", "stop_loop", "on_window_points"):
            assert any(
                f"{panel}_{server}__state.{handler}" in name for name in registered
            ), f"{panel}/{server}.{handler} not registered without page compilation"


def test_route_map_splits_live_and_action_panels(reflex_cfg):
    from helao.core.servers.reflex.app import route_map

    routes = route_map(reflex_cfg, ["live", "action"])
    assert sorted(t.server_key for t in routes["/live"]) == ["GPSIM", "SIM"]
    assert [t.server_key for t in routes["/action"]] == ["CPSIM"]


def test_ingest_registry_discovers_every_panel_target(reflex_cfg):
    """Every launchable panel must be wired, or the browser check proves less.

    CPSIM is the sole ws_data target — the path that shipped two Critical
    defects — so without it the only step that can prove rendering never
    touches it. GPSIM is what lets CPSIM produce any data at all: every OERSIM
    experiment routes through it, and measure_cp needs a composition it picks.
    """
    from helao.core.servers.reflex.ingest import IngestRegistry

    assert sorted(IngestRegistry(reflex_cfg).targets()) == [
        ("CPSIM", "ws_data"),
        ("GPSIM", "ws_live"),
        ("SIM", "ws_live"),
    ]


def test_every_server_in_this_config_can_actually_be_imported(reflex_cfg):
    """A config naming a server that cannot import aborts the group at launch.

    This is not hypothetical: GPSIM had to be pulled from this config when its
    driver's module-level ``import gpflow`` (which needs tensorflow, with no
    Python 3.14 build) made the server unimportable, and it is back only
    because the surrogate now runs on gpytorch. Route composition and
    ``validateConfig`` both pass for such a config -- only launching it fails --
    so nothing else in this suite would notice.
    """
    import os
    from glob import glob
    from importlib import import_module

    root = os.getcwd()
    failures = []
    for key, server in reflex_cfg["servers"].items():
        for code in ("fast", "bokeh", "reflex"):
            module = server.get(code)
            if not module:
                continue
            if code == "reflex":
                candidates = ["helao.core.servers.reflex.app"]
            else:
                hits = glob(
                    os.path.join(
                        root,
                        "helao",
                        "deploy",
                        "*",
                        "servers",
                        server["group"],
                        f"{module}.py",
                    )
                )
                candidates = [
                    "helao.deploy."
                    + h.split("/deploy/")[1].replace(".py", "").replace("/", ".")
                    for h in hits
                ]
            assert candidates, f"{key}: no module found for {code}: {module}"
            last = None
            for candidate in candidates:
                try:
                    import_module(candidate)
                    last = None
                    break
                except Exception as exc:  # noqa: BLE001 - reported below
                    last = f"{type(exc).__name__}: {exc}"
            if last:
                failures.append(f"{key} ({module}): {last}")
    assert not failures, "unimportable servers in goldenreflex:\n" + "\n".join(failures)


def test_calc_eta_does_not_drag_in_the_gp_stack():
    """cpsim must not transitively import a GP stack for four lines of maths.

    calc_eta lived in gpsim_driver, whose module-level GP import made every
    consumer carry it. That stack is gpytorch now rather than gpflow, so this
    is no longer a launch-blocker for CPSIM -- but importing torch to average
    six floats is still wrong, and the coupling is what made a single
    unavailable dependency take down an unrelated server.
    """
    import ast
    import inspect

    from helao.deploy.test.drivers.data import oer_metrics

    def _imported_roots(module):
        """Module names actually imported, ignoring prose in docstrings."""
        tree = ast.parse(inspect.getsource(module))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        return roots

    # Substring-matching the source would trip on this module's own docstring,
    # which names these to explain why the extraction exists.
    heavy = {"gpflow", "tensorflow", "gpytorch", "torch"}
    assert not (_imported_roots(oer_metrics) & heavy)

    assert oer_metrics.calc_eta({"t_s": [0, 1, 2, 3, 4, 5], "erhe_v": [1.5] * 6}) == (
        1.5 - 1.23
    )

    cpsim = __import__("helao.deploy.test.drivers.pstat.cpsim_driver", fromlist=["x"])
    assert "gpsim_driver" not in inspect.getsource(cpsim).split('"""')[-1]


def test_every_panel_module_is_reachable_from_this_config(reflex_cfg):
    from helao.core.servers.reflex.app import panel_targets

    modules = sorted(t.module_name for t in panel_targets(reflex_cfg))
    assert modules == ["gpsim_panel", "oersim_panel", "wssim_panel"]


def test_every_panel_on_every_route_renders(reflex_cfg):
    from helao.core.servers.reflex.app import _render_panel, route_map

    routes = route_map(reflex_cfg, ["live", "action"])
    for path, targets in routes.items():
        for target in targets:
            assert _render_panel(target) is not None, f"{path}:{target.server_key}"


def test_browser_route_is_the_real_page_not_a_stub(reflex_cfg):
    """The stub said the browser was unimplemented. Once it is implemented, a
    passing route test that still renders the stub is worse than no test."""
    from helao.core.servers.data_browser import app_reflex

    from helao.core.servers.reflex.app import build_app

    build_app(reflex_cfg, "UI")
    assert app_reflex.BrowserState.__name__ == "BrowserState"
    assert callable(app_reflex.build_page)


def test_browser_state_handlers_are_registered_without_compiling_pages(reflex_cfg):
    """Same failure mode the panels hit: handlers created inside the lazy
    add_page callable never exist in a --backend-only process, so every
    control on the page silently does nothing."""
    from reflex_base.registry import RegistrationContext

    from helao.core.servers.data_browser.app_reflex import BrowserState
    from helao.core.servers.reflex.app import build_app

    build_app(reflex_cfg, "UI")
    registered = set(RegistrationContext.get().event_handlers)
    # Derived from the class, never hand-spelled: Reflex builds a state's full
    # name from its module path and a snake_cased class name, so a guessed
    # literal would be a test that passes for the wrong reason or fails for no
    # reason.
    prefix = BrowserState.get_full_name()
    for handler in ("scan", "on_filter", "add_selected", "clear_plot"):
        assert (
            f"{prefix}.{handler}" in registered
        ), f"BrowserState.{handler} not registered without page compilation"


def test_operator_route_is_the_real_page_not_a_stub(reflex_cfg):
    """The stub said the operator was unimplemented. A passing route test that
    still renders the stub is worse than no test."""
    from helao.core.servers.operator import app_reflex

    from helao.core.servers.reflex.app import build_app

    build_app(reflex_cfg, "UI")
    assert callable(app_reflex.build_page)
    assert app_reflex.build_page() is not None


def test_operator_state_handlers_are_registered_without_compiling_pages(reflex_cfg):
    """The operator has four states, and every one of them owns controls that
    would silently do nothing if its class were first touched inside the lazy
    add_page callable."""
    from reflex_base.registry import RegistrationContext

    from helao.core.servers.operator.app_reflex import (
        OperatorLibState,
        OperatorPlanState,
        OperatorPlateState,
        OperatorQueueState,
    )
    from helao.core.servers.reflex.app import build_app

    build_app(reflex_cfg, "UI")
    registered = set(RegistrationContext.get().event_handlers)
    expected = {
        OperatorQueueState: ("poll_loop", "control", "move", "remove"),
        OperatorLibState: ("load_libraries", "select_item", "set_param", "enqueue"),
        OperatorPlanState: ("append_selection", "flush", "move_row", "remove_row"),
        OperatorPlateState: ("load_plate", "on_select", "set_sample"),
    }
    for state, handlers in expected.items():
        prefix = state.get_full_name()
        for handler in handlers:
            assert (
                f"{prefix}.{handler}" in registered
            ), f"{state.__name__}.{handler} not registered without page compilation"


def test_operator_backend_is_configured_at_build(reflex_cfg):
    """Without this the page renders but can never reach an orchestrator: the
    per-session backend is built from the config recorded here."""
    from helao.core.servers.operator import app_reflex

    from helao.core.servers.reflex.app import build_app

    app_reflex.reset_settings()
    build_app(reflex_cfg, "UI")
    assert app_reflex.session_backend.__name__ == "session_backend"
    assert app_reflex._SETTINGS.get("server_key") == "UI"
