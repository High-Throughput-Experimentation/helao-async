"""P7f — the hexagon Reflex hosting facade.

The facade must be an IDENTITY over the legacy app: same ``rx.App`` instance,
same pages, same panel states, minted in the same order. Anything else and the
exported bundle stops matching the served backend, which is silent in the
browser (a page that renders and then refuses every WebSocket).

Importing ``helao.hexagon.app.reflex_host`` builds a real Reflex app, so the
config is installed before the first import and this module is imported
through a fixture rather than at file scope.
"""

import os

import pytest

from helao.helpers import config_loader

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
_CFG = os.path.join(
    _REPO_ROOT, "helao", "deploy", "test", "configs", "goldenhexreflex.yml"
)


def _installed_config() -> dict:
    """The installed global config, narrowed. ``config_loader.CONFIG`` is
    Optional, and every use here runs under the fixture that installed it."""
    cfg = config_loader.CONFIG
    assert cfg is not None
    return cfg


@pytest.fixture(scope="module")
def hosted():
    """Install the gate config, then import the facade it routes to.

    ``HELAO_REFLEX_SERVER_KEY`` is what the launcher and the export both set;
    without it the facade falls back to scanning for a reflex server, which is
    a different code path and not the one a launch takes.
    """
    saved_cfg = config_loader.CONFIG
    saved_key = os.environ.get("HELAO_REFLEX_SERVER_KEY")
    cfg, _ = config_loader.read_validated_config(_CFG)
    config_loader.install_global_config(cfg)
    os.environ["HELAO_REFLEX_SERVER_KEY"] = "UI"
    from helao.hexagon.app import reflex_host

    yield reflex_host
    config_loader.CONFIG = saved_cfg
    if saved_key is None:
        os.environ.pop("HELAO_REFLEX_SERVER_KEY", None)
    else:
        os.environ["HELAO_REFLEX_SERVER_KEY"] = saved_key


def test_the_facade_app_is_the_legacy_app_object_itself(hosted):
    """Identity, not equality: a facade that called ``build_app`` again would
    mint a second ``rx.App`` and a second set of state classes, while the
    browser's bundle was compiled against the first -- every panel then sits
    at "connecting" with a handler-not-found KeyError in the backend."""
    from helao.core.servers.reflex import app as legacy

    assert hosted.app is legacy.app


def test_the_facade_registers_panel_handlers_before_any_page(hosted):
    """The ``--backend-only`` trap, re-asserted through the facade.

    ``add_page`` takes a lazy callable a backend-only process never runs, so
    panel state classes must be minted before the pages are added. The facade
    delegates that ordering rather than reimplementing it -- this is what
    would fail if a later edit made it build its own app "just to add a
    hexagon page".
    """
    from reflex_base.registry import RegistrationContext

    registered = set(RegistrationContext.get().event_handlers)
    for panel, server in (
        ("wssim_panel", "sim"),
        ("oersim_panel", "cpsim"),
        ("gpsim_panel", "gpsim"),
    ):
        assert any(
            f"{panel}_{server}__state.render_loop" in name for name in registered
        ), f"{panel}/{server} state not minted through the facade"


def test_the_facade_serves_every_shell_route(hosted):
    from helao.core.servers.reflex.app import SHELL_ROUTES

    registered = set(hosted.app._unevaluated_pages or hosted.app._pages)
    for path in SHELL_ROUTES:
        normalized = path if path != "/" else "index"
        assert any(
            normalized.strip("/") in str(r).strip("/") for r in registered
        ), f"route {path} missing; registered={registered}"


def test_panels_still_resolve_with_the_deployment_key_set_to_hexagon(hosted):
    """``deployment: hexagon`` is not inert for the Reflex stack.

    ``app._build_from_global_config`` copies the server's ``deployment:`` into
    ``CONFIG["deployment"]``, and ``deployment_search_order`` puts that value
    FIRST when resolving a panel module by short name. Under hexagon routing
    the first candidate is therefore ``helao.deploy.hexagon.servers.reflex.*``,
    which does not exist -- the panels are found only because the fallback scan
    reaches the config's real deployment. If that fallback ever narrows, every
    panel on a hexagon-hosted page becomes an error card and nothing else in
    this suite would notice.
    """
    from helao.ui.shared.discovery import (
        deployment_search_order,
        resolve_panel_module,
    )

    cfg = _installed_config()
    saved = cfg.get("deployment")
    # Exactly what reflex_launcher.py and app._build_from_global_config both
    # write into the installed config for this server entry.
    cfg["deployment"] = "hexagon"
    resolve_panel_module.cache_clear()
    try:
        order = deployment_search_order()
        assert order[0] == "hexagon"
        assert "test" in order, order
        for panel in ("wssim_panel", "oersim_panel", "gpsim_panel"):
            module = resolve_panel_module(panel)
            assert module.__name__.startswith("helao.deploy.test.servers.reflex.")
    finally:
        if saved is None:
            cfg.pop("deployment", None)
        else:
            cfg["deployment"] = saved
        resolve_panel_module.cache_clear()


def test_the_composition_is_real_and_carries_a_ui_host(hosted):
    from helao.hexagon.app.wiring import VIS_REQUIRED
    from helao.hexagon.ports.ui_host import UiHostPort

    wiring = hosted.WIRING
    assert isinstance(wiring.ui_host, hosted.ReflexAppUiHost)
    assert isinstance(wiring.ui_host, UiHostPort)
    # would raise if any required port were unwired
    wiring.require(*VIS_REQUIRED)
    assert wiring.config.server_cfg("UI")["reflex"] == "helao_ui"


def test_build_ui_app_returns_the_process_app(hosted):
    """The port's Reflex face. One app object per process (Reflex's state
    registry is process-global), so this returns the built app rather than
    constructing another."""
    assert hosted.ReflexAppUiHost().build_ui_app(_installed_config()) is hosted.app


def test_build_ui_app_refuses_a_different_config(hosted):
    """Silently returning this process's app for another group's config would
    serve a UI pointed at the wrong orchestrator."""
    other = dict(_installed_config())
    other["loaded_config_path"] = "/somewhere/else/othergroup.yml"
    with pytest.raises(ValueError) as exc:
        hosted.ReflexAppUiHost().build_ui_app(other)
    assert "othergroup.yml" in str(exc.value)


def test_the_reflex_host_defers_the_document_faces(hosted):
    """Mirror image of ``BokehServerUiHost``, which defers ``build_ui_app``:
    a Reflex process hosts no Bokeh documents, and a fake that silently did
    nothing would be worse than one that says so."""
    from helao.hexagon.adapters.errors import HexagonDeferred

    host = hosted.ReflexAppUiHost()
    with pytest.raises(HexagonDeferred):
        host.start_document_host({}, "127.0.0.1", 5099)
    with pytest.raises(HexagonDeferred):
        host.stop(object())


def test_composition_fails_loud_without_an_installed_config(hosted, monkeypatch):
    """Fail-loud composition (spec §4.5): the import raises rather than
    serving a half-built UI. Exercised through the same function the module
    body calls, since the module body has already run by now."""
    monkeypatch.setattr(config_loader, "CONFIG", None)
    with pytest.raises(Exception) as exc:
        hosted.build_host_wiring("UI")
    assert "CONFIG" in str(exc.value) or "config" in str(exc.value).lower()


def test_composition_fails_loud_on_a_server_key_the_config_lacks(hosted):
    with pytest.raises(KeyError):
        hosted.build_host_wiring("NOT_A_SERVER")


def test_the_facade_knows_which_server_it_serves(hosted):
    assert hosted.server_key == "UI"
