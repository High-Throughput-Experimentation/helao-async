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
    assert sorted(t.server_key for t in routes["/live"]) == ["SIM"]
    assert [t.server_key for t in routes["/action"]] == ["CPSIM"]


def test_ingest_registry_discovers_every_panel_target(reflex_cfg):
    """Every launchable panel must be wired, or the browser check proves less.

    CPSIM is the sole ws_data target — the path that shipped two Critical
    defects — so without it the only step that can prove rendering never
    touches it. GPSIM is excluded on purpose: gpsim_driver imports gpflow,
    which needs tensorflow, and tensorflow has no Python 3.14 release, so that
    server cannot import at all.
    """
    from helao.core.servers.reflex.ingest import IngestRegistry

    assert sorted(IngestRegistry(reflex_cfg).targets()) == [
        ("CPSIM", "ws_data"),
        ("SIM", "ws_live"),
    ]


def test_every_server_in_this_config_can_actually_be_imported(reflex_cfg):
    """A config naming a server that cannot import aborts the group at launch.

    This is not hypothetical: GPSIM was wired in here until its driver's
    module-level ``import gpflow`` (which needs tensorflow, unavailable on
    Python 3.14) made the server unimportable. Route composition and
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


def test_calc_eta_does_not_drag_in_the_deprecated_gp_simulator():
    """cpsim must not transitively import gpflow for four lines of arithmetic.

    calc_eta lived in gpsim_driver, whose module-level ``import gpflow`` made
    every consumer depend on tensorflow. Keeping it in a dependency-free module
    is what lets CPSIM -- the config's only ws_data server -- launch at all.
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
    # which names gpflow to explain why the extraction exists.
    heavy = {"gpflow", "tensorflow"}
    assert not (_imported_roots(oer_metrics) & heavy)

    assert oer_metrics.calc_eta({"t_s": [0, 1, 2, 3, 4, 5], "erhe_v": [1.5] * 6}) == (
        1.5 - 1.23
    )

    cpsim = __import__("helao.deploy.test.drivers.pstat.cpsim_driver", fromlist=["x"])
    assert "gpsim_driver" not in inspect.getsource(cpsim).split('"""')[-1]


def test_every_panel_module_is_reachable_from_this_config(reflex_cfg):
    from helao.core.servers.reflex.app import panel_targets

    modules = sorted(t.module_name for t in panel_targets(reflex_cfg))
    assert modules == ["oersim_panel", "wssim_panel"]


def test_every_panel_on_every_route_renders(reflex_cfg):
    from helao.core.servers.reflex.app import _render_panel, route_map

    routes = route_map(reflex_cfg, ["live", "action"])
    for path, targets in routes.items():
        for target in targets:
            assert _render_panel(target) is not None, f"{path}:{target.server_key}"
