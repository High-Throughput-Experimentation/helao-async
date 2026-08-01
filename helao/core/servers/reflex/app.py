"""The single multi-page Reflex app for one HELAO orchestration group.

One process, one frontend build, and one route per page — rather than the
Bokeh stack's one server process and port per config entry. Panels are
discovered from the same ``live_vis`` / ``action_vis`` config keys the Bokeh
visualizers use, so a config that already declares visualizers needs no new
keys.

A panel module must expose:

* ``WS_PATH`` — ``"ws_live"`` or ``"ws_data"``
* ``STATE_BASE`` — :class:`LiveVisState` or :class:`ActionVisState`
* ``build(server_key, state_cls) -> rx.Component``
"""

__all__ = ["PanelTarget", "panel_targets", "route_map", "build_app", "app"]

from dataclasses import dataclass

import reflex as rx
from fastapi import FastAPI

from helao.core.servers.reflex.discovery import resolve_panel_module
from helao.core.servers.reflex.ingest import (
    VIS_KEY_TO_WS_PATH,
    IngestRegistry,
    set_registry,
)
from helao.core.servers.reflex import plots
from helao.core.servers.reflex.state import make_panel_state
from helao.core.servers.reflex.xy_component import make_buffer_router
from helao.helpers import config_loader
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Routes always registered so the navigation shell is complete even when a
#: page has no content yet.
SHELL_ROUTES = ("/", "/live", "/action", "/operator", "/browser")

#: Page name -> the config key whose panels belong on it.
PAGE_TO_VIS_KEY = {"live": "live_vis", "action": "action_vis"}


@dataclass(frozen=True)
class PanelTarget:
    """One panel to render: a module bound to a server and a WebSocket path.

    Attributes:
        server_key: Action server the panel reads.
        module_name: Panel module short name.
        ws_path: ``ws_live`` or ``ws_data``.
        vis_key: The config key that produced this target.
    """

    server_key: str
    module_name: str
    ws_path: str
    vis_key: str


def panel_targets(world_cfg: dict, limit_vis=None) -> list:
    """Discover every panel declared by the config's action servers.

    Args:
        world_cfg: The loaded HELAO world config.
        limit_vis: Optional allow-list of server keys, mirroring the Bokeh
            visualizers' ``limit_vis`` server param.

    Returns:
        list: :class:`PanelTarget` entries, config order preserved.
    """
    targets = []
    for server_key, server_cfg in (world_cfg.get("servers") or {}).items():
        if not isinstance(server_cfg, dict):
            continue
        if limit_vis and server_key not in limit_vis:
            continue
        for vis_key, ws_path in VIS_KEY_TO_WS_PATH.items():
            module_names = server_cfg.get(vis_key)
            if not module_names:
                continue
            if isinstance(module_names, str):
                module_names = [module_names]
            for module_name in module_names:
                targets.append(PanelTarget(server_key, module_name, ws_path, vis_key))
    return targets


def route_map(world_cfg: dict, pages, limit_vis=None) -> dict:
    """Group panel targets into routes.

    Every entry of :data:`SHELL_ROUTES` is present in the result, with an empty
    list where a page was not requested or has no panels — a requested-but-empty
    page still renders and says so, rather than 404ing.

    Args:
        world_cfg: The loaded HELAO world config.
        pages: Page names from the Reflex server's ``params.pages``.
        limit_vis: Optional allow-list of server keys.

    Returns:
        dict: ``{route_path: [PanelTarget, ...]}``.
    """
    wanted = set(pages or [])
    all_targets = panel_targets(world_cfg, limit_vis=limit_vis)
    routes = {path: [] for path in SHELL_ROUTES}
    for page, vis_key in PAGE_TO_VIS_KEY.items():
        if page not in wanted:
            continue
        routes[f"/{page}"] = [t for t in all_targets if t.vis_key == vis_key]
    return routes


def _error_card(title: str, detail: str):
    """Render a visible failure instead of a blank slot."""
    return rx.card(
        rx.vstack(
            rx.heading(title, size="3", color_scheme="red"),
            rx.text(detail, size="2"),
            align="start",
            spacing="2",
        ),
        width="100%",
    )


def _render_panel(target: PanelTarget):
    """Build one panel, degrading to an error card if its module misbehaves.

    A broken panel module must not take down the whole page, so import and
    build failures are caught here and rendered in place.
    """
    try:
        module = resolve_panel_module(target.module_name)
    except ModuleNotFoundError as exc:
        LOGGER.warning(f"reflex panel module missing: {exc}")
        return _error_card(f"{target.server_key}: panel module not found", str(exc))
    try:
        state_cls = make_panel_state(
            target.module_name,
            target.server_key,
            module.STATE_BASE,
            module.WS_PATH,
        )
        return module.build(target.server_key, state_cls)
    except Exception as exc:
        LOGGER.warning(f"reflex panel build failed for {target.server_key}: {exc}")
        return _error_card(
            f"{target.server_key}: panel failed to build",
            f"{type(exc).__name__}: {exc}",
        )


def _nav():
    """Render the shared navigation bar."""
    return rx.hstack(
        rx.heading("HELAO", size="5"),
        rx.spacer(),
        rx.link("Live", href="/live"),
        rx.link("Action", href="/action"),
        rx.link("Operator", href="/operator"),
        rx.link("Browser", href="/browser"),
        width="100%",
        padding="0.75em 1em",
        align="center",
        spacing="4",
    )


def _page(title: str, body):
    """Wrap page content in the shared shell."""
    return rx.vstack(
        _nav(),
        rx.divider(),
        rx.heading(title, size="6", padding_x="1em"),
        body,
        width="100%",
        spacing="3",
        padding_bottom="2em",
    )


def _panel_page(title: str, targets: list, empty_note: str):
    """Render a page of panels, or an explanatory note when there are none."""
    if not targets:
        return _page(title, rx.text(empty_note, padding_x="1em"))
    return _page(
        title,
        rx.vstack(
            *[_render_panel(t) for t in targets],
            width="100%",
            spacing="4",
            padding_x="1em",
        ),
    )


def _index_page(routes: dict):
    """Render the route index."""
    return _page(
        "Routes",
        rx.vstack(
            *[
                rx.hstack(
                    rx.link(path, href=path),
                    rx.text(f"{len(targets)} panel(s)", size="2"),
                    spacing="3",
                )
                for path, targets in routes.items()
                if path != "/"
            ],
            align="start",
            spacing="2",
            padding_x="1em",
        ),
    )


def _stub_page(title: str, spec_note: str):
    """Render a placeholder route that states what will fill it."""
    return _page(title, rx.text(spec_note, padding_x="1em"))


def build_app(world_cfg: dict, server_key: str):
    """Build the Reflex app for one orchestration group.

    Args:
        world_cfg: The loaded HELAO world config.
        server_key: Config key of the Reflex server entry.

    Returns:
        rx.App: The configured app, with ingest registered on its lifespan.
    """
    server_cfg = (world_cfg.get("servers") or {}).get(server_key) or {}
    params = server_cfg.get("params") or {}
    pages = params.get("pages") or ["live", "action"]
    limit_vis = params.get("limit_vis") or []
    routes = route_map(world_cfg, pages, limit_vis=limit_vis)

    registry = IngestRegistry(world_cfg)
    set_registry(registry)

    # The buffer route carries bulk column data out-of-band, so megabyte float
    # arrays never traverse Reflex's JSON state channel. `api_transformer` is
    # the public seam for this: Reflex 0.9.7 exposes no `app.api` before build
    # and `_api` is private.
    backend = FastAPI()
    backend.include_router(make_buffer_router(plots.STORE))

    application = rx.App(api_transformer=backend)

    application.add_page(lambda: _index_page(routes), route="/", title="HELAO")
    application.add_page(
        lambda: _panel_page(
            "Live visualizers",
            routes["/live"],
            "No server in this config declares a `live_vis` panel.",
        ),
        route="/live",
        title="HELAO live",
    )
    application.add_page(
        lambda: _panel_page(
            "Action visualizers",
            routes["/action"],
            "No server in this config declares an `action_vis` panel.",
        ),
        route="/action",
        title="HELAO action",
    )
    application.add_page(
        lambda: _stub_page(
            "Operator",
            "The Reflex operator is not implemented yet. Use the Bokeh "
            "standalone operator; a follow-up spec covers this page.",
        ),
        route="/operator",
        title="HELAO operator",
    )
    application.add_page(
        lambda: _stub_page(
            "Data browser",
            "The Reflex data browser is not implemented yet. Use the Bokeh "
            "data_browser; a follow-up spec covers this page.",
        ),
        route="/browser",
        title="HELAO browser",
    )

    async def _start_ingest():
        registry.start()
        LOGGER.info(f"reflex ingest started for targets: {registry.targets()}")

    application.register_lifespan_task(_start_ingest)
    return application


def _build_from_global_config():
    """Build the app from the installed global config, if there is one."""
    cfg = config_loader.CONFIG
    if not cfg:
        return rx.App()
    import os

    key = os.environ.get("HELAO_REFLEX_SERVER_KEY", "")
    if not key:
        for candidate, entry in (cfg.get("servers") or {}).items():
            if isinstance(entry, dict) and entry.get("reflex"):
                key = candidate
                break
    return build_app(cfg, key)


#: Module-level app imported by the Reflex CLI entrypoint.
app = _build_from_global_config()
