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


def test_route_map_puts_the_sim_panel_on_live(reflex_cfg):
    from helao.core.servers.reflex.app import route_map

    routes = route_map(reflex_cfg, ["live", "action"])
    assert sorted(t.server_key for t in routes["/live"]) == ["GPSIM", "SIM"]
    assert [t.server_key for t in routes["/action"]] == ["CPSIM"]


def test_ingest_registry_discovers_every_panel_target(reflex_cfg):
    """All three panels must be wired, or the browser check proves only one.

    In particular CPSIM is the sole ws_data target — the path that shipped two
    Critical defects — so without it the only step that can prove rendering
    never touches it.
    """
    from helao.core.servers.reflex.ingest import IngestRegistry

    assert sorted(IngestRegistry(reflex_cfg).targets()) == [
        ("CPSIM", "ws_data"),
        ("GPSIM", "ws_live"),
        ("SIM", "ws_live"),
    ]


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
