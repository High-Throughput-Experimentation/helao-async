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

__all__ = [
    "PanelTarget",
    "as_list",
    "as_dict",
    "panel_targets",
    "route_map",
    "build_app",
    "app",
]

import contextlib
import os
from dataclasses import dataclass

import reflex as rx
from fastapi import FastAPI

# Imported at module scope, not inside the page callable: creating the state
# class is what registers its event handlers, and `--backend-only` never
# evaluates a page callable. No cycle -- app_reflex reaches back only as far as
# `plots`, which knows nothing about this module.
from helao.core.servers.data_browser.app_reflex import BrowserState
from helao.core.servers.data_browser.app_reflex import build_page as browser_page
from helao.core.servers.operator.app_reflex import (
    OperatorLibState,
    OperatorPlanState,
    OperatorPlateState,
    OperatorQueueState,
    OperatorSpecState,
)
from helao.core.servers.operator.app_reflex import build_page as operator_page
from helao.core.servers.operator.app_reflex import configure as configure_operator
from helao.core.servers.palette import (
    CHART_CHROME,
    reflex_gridjs_header_css,
    reflex_page_class,
)
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


def as_list(value) -> list:
    """Coerce a config value to a list, tolerating a bare scalar.

    YAML makes ``pages: live`` and ``pages: [live]`` easy to confuse, and the
    former silently degrades: ``set("live")`` is ``{"l","i","v","e"}``, so every
    requested page vanishes with no error. Same hazard for ``limit_vis``, where
    membership degrades to a substring test.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def as_dict(value, *, what: str) -> dict:
    """Return ``value`` when it is a mapping, otherwise ``{}`` with a warning.

    ``build_app`` runs at import time, so an unguarded ``.get`` on a malformed
    block takes down the module — and with it the Reflex CLI entrypoint.
    """
    if isinstance(value, dict):
        return value
    if value is not None:
        LOGGER.warning(f"{what} is not a mapping ({type(value).__name__}); ignoring")
    return {}


def declared_ws_path(module_name: str, key_default: str) -> str:
    """The socket a panel module reads, falling back to the config key's.

    ``live_vis`` normally implies ``ws_live``, but the key says which *page* a
    panel belongs on and the module says which *socket* it reads -- and those
    genuinely differ: a potentiostat panel can belong on the live page while
    reading per-action packets. Deriving the socket from the key alone
    subscribes the ingest to one path while the panel waits on another, and
    the panel then reports no ingest for a path nothing is feeding.

    Unresolvable modules keep the key's default: discovery must not break on a
    module that cannot be imported, and :func:`_render_panel` already renders
    that case as an error card.
    """
    try:
        module = resolve_panel_module(module_name)
    except Exception:
        return key_default
    declared = getattr(module, "WS_PATH", None)
    if isinstance(declared, str) and declared in VIS_KEY_TO_WS_PATH.values():
        return declared
    return key_default


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
    allowed = as_list(limit_vis)
    for server_key, server_cfg in (world_cfg.get("servers") or {}).items():
        if not isinstance(server_cfg, dict):
            continue
        if allowed and server_key not in allowed:
            continue
        for vis_key, ws_path in VIS_KEY_TO_WS_PATH.items():
            module_names = server_cfg.get(vis_key)
            if not module_names:
                continue
            for module_name in as_list(module_names):
                targets.append(
                    PanelTarget(
                        server_key,
                        module_name,
                        declared_ws_path(module_name, ws_path),
                        vis_key,
                    )
                )
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
    wanted = set(as_list(pages))
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
            rx.heading(title, size="3", class_name="text-red-600"),
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
    except Exception as exc:
        # A module that exists but raises while importing -- a bad transitive
        # import, a NameError, any bug in a deployment's panel. Catching only
        # ModuleNotFoundError here would let that escape and take down the
        # whole page, defeating the isolation this function exists for.
        LOGGER.exception(f"reflex panel module failed to import: {exc}")
        return _error_card(
            f"{target.server_key}: panel module failed to import",
            f"{type(exc).__name__}: {exc}",
        )
    try:
        state_cls = make_panel_state(
            target.module_name,
            target.server_key,
            module.STATE_BASE,
            module.WS_PATH,
        )
        # The tick is added here, not by the panel module: it must exist in
        # the tree so it stops when the tab closes, and adding it here means
        # panel modules -- including ones in deployments outside this repo --
        # need no change to stop leaking a render loop per abandoned tab.
        return rx.fragment(
            module.build(target.server_key, state_cls),
            rx.moment(
                interval=state_cls.tick_ms,
                on_change=state_cls.render_tick,
                display="none",
            ),
        )
    except Exception as exc:
        # .exception, not .warning: without the traceback a real bug in an
        # otherwise-working panel is far harder to place.
        LOGGER.exception(f"reflex panel build failed for {target.server_key}: {exc}")
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


def _page(title: str, body, route: str):
    """Wrap page content in the shared shell, tinted for *route*.

    The tint is the functional-section signal: each route carries its own canvas
    so a glance tells you which page you are on. It goes on this outermost
    ``vstack`` rather than on ``html``/``body`` because Reflex's ``App.style``
    cannot reach ``<html>`` (see :func:`build_app`), and it carries
    ``min-h-screen`` so a short page does not read as two colours.

    Args:
        title: Page heading.
        body: Page content.
        route: The route being rendered, a key of ``REFLEX_PAGE_TINTS``.
    """
    return rx.vstack(
        _nav(),
        rx.divider(),
        rx.heading(title, size="6", padding_x="1em"),
        body,
        width="100%",
        spacing="3",
        padding_bottom="2em",
        class_name=reflex_page_class(route),
    )


def _panel_page(title: str, targets: list, empty_note: str, route: str):
    """Render a page of panels, or an explanatory note when there are none."""
    if not targets:
        return _page(title, rx.text(empty_note, padding_x="1em"), route)
    return _page(
        title,
        rx.vstack(
            *[_render_panel(t) for t in targets],
            width="100%",
            spacing="4",
            padding_x="1em",
        ),
        route,
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
        "/",
    )


def _stub_page(title: str, spec_note: str, route: str = "/"):
    """Render a placeholder route that states what will fill it."""
    return _page(title, rx.text(spec_note, padding_x="1em"), route)


def _ensure_panel_states(routes: dict) -> None:
    """Mint every panel's state class at build time.

    ``add_page`` takes a *callable*, which Reflex evaluates only when it
    compiles the frontend. ``reflex run --backend-only`` never compiles, so a
    state class created inside that callable is never created in the serving
    process at all. Reflex registers a state's event handlers when the class is
    created, and the browser runs a bundle built by a separate ``reflex export``
    process where the pages *were* compiled -- so it calls handlers the backend
    has never heard of, and every panel sits at "connecting" forever::

        KeyError: No registered handler found for event:
        ...wssim_panel_sim__state.render_loop

    Minting the classes here, before any page is added, keeps the two processes
    in agreement; :func:`_render_panel` then reuses the cached classes.

    Import and build failures stay silent beyond a log line: ``_render_panel``
    is what turns them into a visible error card, and it runs per panel.

    Args:
        routes: The mapping from :func:`route_map`.
    """
    for targets in routes.values():
        for target in targets:
            try:
                module = resolve_panel_module(target.module_name)
                make_panel_state(
                    target.module_name,
                    target.server_key,
                    module.STATE_BASE,
                    module.WS_PATH,
                )
            except Exception as exc:
                LOGGER.warning(
                    f"reflex panel state not created for {target.server_key} "
                    f"({target.module_name}): {type(exc).__name__}: {exc}"
                )


def build_app(world_cfg: dict, server_key: str):
    """Build the Reflex app for one orchestration group.

    Args:
        world_cfg: The loaded HELAO world config.
        server_key: Config key of the Reflex server entry.

    Returns:
        rx.App: The configured app, with ingest registered on its lifespan.
    """
    server_cfg = as_dict(
        (world_cfg.get("servers") or {}).get(server_key), what=f"server '{server_key}'"
    )
    params = as_dict(server_cfg.get("params"), what=f"server '{server_key}' params")
    pages = as_list(params.get("pages")) or ["live", "action"]
    limit_vis = as_list(params.get("limit_vis"))
    routes = route_map(world_cfg, pages, limit_vis=limit_vis)

    registry = IngestRegistry(world_cfg)
    set_registry(registry)

    # Before add_page: the page callables are lazy, and the backend-only
    # process never runs them.
    _ensure_panel_states(routes)
    # Same reason, for the browser: Reflex registers a state's event handlers
    # when the class is created, and a class first touched inside add_page's
    # callable is never created in a `--backend-only` process -- leaving every
    # control on the page silently doing nothing. Importing at module scope is
    # what creates it; this reference is what keeps that import from looking
    # unused and being removed.
    assert BrowserState is not None
    # Same for the operator's four states.
    assert None not in (
        OperatorQueueState,
        OperatorLibState,
        OperatorPlanState,
        OperatorPlateState,
        OperatorSpecState,
    )
    # The operator's backend is built per session from this config; without
    # this the page renders but can never reach an orchestrator.
    configure_operator(world_cfg, server_key)

    # The buffer route carries bulk column data out-of-band, so megabyte float
    # arrays never traverse Reflex's JSON state channel. `api_transformer` is
    # the public seam for this: Reflex 0.9.7 exposes no `app.api` before build
    # and `_api` is private.
    backend = FastAPI()
    backend.include_router(make_buffer_router(plots.STORE))

    # `App.style={":root": ...}` does *not* reach `<html>`: Reflex merges
    # `App.style` per-component (`_get_component_style` matches only on
    # component type), so an unmatched string key like ":root" falls through
    # to the generic nested-selector path and Emotion serializes it as a
    # *descendant* rule -- `.css-XXXX *:root{...}` -- scoped under whichever
    # wrapper component happened to carry it. `:root` only ever matches
    # `<html>`, and `<html>` is never a descendant of anything in the page
    # body, so the rule can never match and the properties never apply
    # anywhere (confirmed empty via `getComputedStyle` on every element).
    # A real `<style>` tag in `<head>` is a genuine top-level rule instead.
    #
    # The gridjs header rule rides the same seam. It cannot be a Tailwind
    # utility: `rx.data_table` does not forward `class_name` to the grid, and
    # gridjs's own `th.gridjs-th` is unlayered CSS, which outranks anything in
    # `@layer utilities`. See `palette.reflex_gridjs_header_css`.
    _root_vars = "; ".join(f"{k}: {v}" for k, v in CHART_CHROME.items())
    application = rx.App(
        api_transformer=backend,
        head_components=[
            rx.el.style(f":root {{ {_root_vars}; }}"),
            rx.el.style(reflex_gridjs_header_css()),
        ],
    )

    application.add_page(lambda: _index_page(routes), route="/", title="HELAO")
    application.add_page(
        lambda: _panel_page(
            "Live visualizers",
            routes["/live"],
            "No server in this config declares a `live_vis` panel.",
            "/live",
        ),
        route="/live",
        title="HELAO live",
    )
    application.add_page(
        lambda: _panel_page(
            "Action visualizers",
            routes["/action"],
            "No server in this config declares an `action_vis` panel.",
            "/action",
        ),
        route="/action",
        title="HELAO action",
    )
    application.add_page(
        lambda: _page("Operator", operator_page(), "/operator"),
        route="/operator",
        title="HELAO operator",
    )
    application.add_page(
        lambda: _page("Data browser", browser_page(), "/browser"),
        route="/browser",
        title="HELAO browser",
    )

    @contextlib.asynccontextmanager
    async def _ingest_lifespan():
        """Own the ingest registry for the app's lifetime.

        An asynccontextmanager, not a plain coroutine: Reflex tracks the former
        through an ``AsyncExitStack`` and awaits its teardown, while a plain
        coroutine is only ``create_task``-ed and cancelled. Since
        ``registry.start()`` returns immediately after spawning the drain tasks,
        a plain coroutine would leave nothing to cancel and every ``WsIngest``
        loop would outlive the app.
        """
        registry.start()
        LOGGER.info(f"reflex ingest started for targets: {registry.targets()}")
        try:
            yield
        finally:
            await registry.stop()
            LOGGER.info("reflex ingest stopped")

    application.register_lifespan_task(_ingest_lifespan)
    return application


def _build_from_global_config():
    """Build the app from the installed global config, loading it if needed.

    ``reflex_launcher`` spawns ``reflex run --backend-only`` as a *child*
    process, and ``reflex export`` runs in its own process too. Both import this
    module fresh, where ``config_loader.CONFIG`` is ``None`` -- it is installed
    only in the launcher's own process. Without reading ``HELAO_REFLEX_CONFIG``
    here, both build a bare ``rx.App()`` with zero pages: the backend serves
    nothing, and the exported bundle ships no routes at all while still looking
    plausible, because assets are copied verbatim regardless of page content.
    """
    cfg = config_loader.CONFIG
    if not cfg:
        conf_arg = os.environ.get("HELAO_REFLEX_CONFIG")
        if conf_arg:
            cfg_dict, _validated = config_loader.read_validated_config(conf_arg)
            config_loader.install_global_config(cfg_dict)
            cfg = config_loader.CONFIG
            # bokeh_launcher sets this in its own process; the Reflex backend is
            # a child that loads the config itself, so it must too. Without it
            # deployment_search_order never tries the config's own deployment
            # and every panel resolves to "module not found".
            if cfg is not None:
                key = os.environ.get("HELAO_REFLEX_SERVER_KEY", "")
                entry = (cfg.get("servers") or {}).get(key) or {}
                cfg["deployment"] = entry.get(
                    "deployment",
                    os.path.basename(
                        os.path.dirname(
                            os.path.dirname(cfg.get("loaded_config_path", ""))
                        )
                    ),
                )
    if not cfg:
        LOGGER.warning(
            "no HELAO config available (HELAO_REFLEX_CONFIG unset and none "
            "installed); building an empty app with no routes"
        )
        return rx.App()

    key = os.environ.get("HELAO_REFLEX_SERVER_KEY", "")
    if not key:
        for candidate, entry in (cfg.get("servers") or {}).items():
            if isinstance(entry, dict) and entry.get("reflex"):
                key = candidate
                break
    return build_app(cfg, key)


#: Module-level app imported by the Reflex CLI entrypoint.
app = _build_from_global_config()
