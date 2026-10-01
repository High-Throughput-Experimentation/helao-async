"""Hexagon composition root (spec §4.5).

The ONLY layer that constructs FastAPI objects and wires adapters into
ports. Fail loud (F2b): build_wiring raises without an installed CONFIG;
each makeApp requires its composition's consumed port set BEFORE building
the app — a missing adapter aborts startup, never a silent fake. The
co-located RPC mirror (spec §7.1) is inherited from HelaoFastAPI's startup
hook (ROUTER on http_port+10000, configured-host bind with 0.0.0.0
fallback). Launcher routing: the helao/deploy/hexagon/ action and visualizer
shims call makeActionApp / makeVisApp via the per-server
`deployment: hexagon` config key — zero launcher edits, per-config atomic
cut-over/rollback. The orchestrator shims construct an OrchHost directly and
do not come through here.

makeActionApp composes native hosts only: the module it names must return an
ActionHost from makeApp, and anything else is refused when the app is built
(B7b, D-B7b.2)."""

import os
from importlib import import_module

from helao.helpers import helao_logging as logging
from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.legacy.clock import LegacyClockAdapter
from helao.hexagon.adapters.legacy.config import from_global_config
from helao.hexagon.adapters.legacy.health import LegacyHealthAdapter
from helao.hexagon.adapters.legacy.logging_adapter import LegacyLoggingAdapter
from helao.hexagon.adapters.legacy.state_persistence import QueuePckStore
from helao.hexagon.adapters.legacy.status import DispatcherStatusAdapter
from helao.hexagon.adapters.legacy.transport import LegacyTransportAdapter
from helao.hexagon.adapters.native.artifact_store import NativeArtifactStoreAdapter
from helao.hexagon.adapters.native.data_sink import NativeDataSinkAdapter
from helao.hexagon.adapters.native.ws_publish import WsPublishBridge
from helao.hexagon.app.wiring import (
    ACTION_REQUIRED,
    VIS_REQUIRED,
    PortWiring,
)

__all__ = ["build_wiring", "makeActionApp", "makeVisApp"]

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def _is_native_host(app) -> bool:
    """True when ``app`` is a native host (an ``ActionHost`` or a subclass).

    ``makeActionApp`` refuses anything else at build time. ``OrchHost``
    subclasses ``ActionHost``, so it passes too.

    Imported inside the function: ``action_host`` imports this module's
    siblings, and a module-level import here closes that cycle.
    """
    from helao.hexagon.app.action_host import ActionHost

    return isinstance(app, ActionHost)


def build_wiring(server_key: str) -> PortWiring:
    config = from_global_config()  # raises when CONFIG is not installed
    root = config.root()  # KeyError -> loud, like helao_dirs
    log_root = os.path.join(root, "LOGS")
    scfg = config.server_cfg(server_key)  # KeyError -> loud, like the launcher
    clock = LegacyClockAdapter.from_offset_file(log_root)
    return PortWiring(
        config=config,
        logging=LegacyLoggingAdapter(),
        clock=clock,
        transport=LegacyTransportAdapter(config),
        state_persistence=QueuePckStore(root),
        status=DispatcherStatusAdapter(
            server_key, own_host=scfg["host"], own_port=scfg["port"]
        ),
        health=LegacyHealthAdapter(),
        # P2b-1 native write runtime; ActionHost binds itself to it
        # (artifact_store.meta_writer_for(host)) when it is constructed.
        artifact_store=NativeArtifactStoreAdapter(config=config, clock=clock),
        data_sink=NativeDataSinkAdapter(),
    )


def makeActionApp(server_key: str, legacy_module: str):
    """Build ``legacy_module.makeApp(server_key)`` under a composed wiring.

    The module must return a native host. The check runs here, while the app
    is being built, rather than in the startup event: a failure there reaches
    uvicorn only as ``SystemExit(3)``, so the server never binds and nothing
    names the module. ``legacy_module`` keeps its name until B7c.
    """
    wiring = build_wiring(server_key)
    wiring.require(*ACTION_REQUIRED)
    app = import_module(legacy_module).makeApp(server_key)
    if not _is_native_host(app):
        raise TypeError(
            f"{legacy_module}.makeApp returned {type(app).__name__}, not an ActionHost"
        )
    app.hexagon_wiring = wiring
    app.hexagon_ws_bridge = None

    # Registered AFTER ActionHost's own startup handler (Starlette preserves
    # registration order), so the host's fan-out queues are live when the
    # bridge is bound to them.
    @app.on_event("startup")
    async def _hexagon_ws_bridge_startup():
        # P2b-2 (D3): the WS publish bridge publishes onto the host's fan-out
        # queues. ACTION apps only: an OrchHost serves its own /ws_* relays.
        if not isinstance(wiring.status, DispatcherStatusAdapter):
            raise UnwiredPortError(
                "WS publish bridge requires DispatcherStatusAdapter status wiring"
            )
        status_adapter = wiring.status
        bridge = WsPublishBridge(app.base.status_q, app.base.data_q, app.base.live_q)
        status_adapter.bind_publish_bridge(bridge)
        app.hexagon_ws_bridge = bridge

    return app


def makeVisApp(legacy_module, doc, confPrefix, server_key, helao_repo_root):
    """P7e: host a legacy Bokeh app UNMODIFIED, under a real composition.

    RENDERING is still entirely the legacy module's (D1/D2 facade
    discipline) — native panel consumption of the wiring is post-parity, so
    the browser DOM must be byte-identical to the legacy path. What P7e adds
    is that the PROCESS is now composed rather than hexagon in name only:

    * ``build_wiring`` runs, so an uninstalled CONFIG, a missing ``root:``,
      or a server key the config does not carry aborts the session loudly
      instead of half-rendering;
    * a ``BokehServerUiHost`` (P7d) fills the ``ui_host`` slot — the port
      that makes this composition a UI host, and the only sanctioned way for
      anything downstream to construct a Bokeh ``Server``;
    * ``VIS_REQUIRED`` is enforced BEFORE the legacy module is imported, so
      a broken composition never reaches the render.

    The wiring rides on the per-session ``Document`` as
    ``doc.hexagon_wiring`` — the Bokeh analogue of ``app.hexagon_wiring``.
    A Document's lifetime IS the browser session's, which is exactly the
    lifetime of the panels that will consume it. ``HelaoBokehAPI`` still
    self-configures from ``config_loader.CONFIG`` (server_api.py) and reads
    none of this; the attachment is purely additive.
    """
    from helao.hexagon.app.ui_host import BokehServerUiHost

    wiring = build_wiring(server_key)
    wiring.ui_host = BokehServerUiHost()
    wiring.require(*VIS_REQUIRED)
    doc.hexagon_wiring = wiring
    out = import_module(legacy_module).makeBokehApp(
        doc, confPrefix, server_key, helao_repo_root
    )
    _refresh_loaded_modules(wiring, server_key)
    return out


def _refresh_loaded_modules(wiring, server_key) -> None:
    """Re-snapshot this process's loaded modules for the hot-reload watcher.

    A bokeh server has no ``/loaded_modules`` route, so the watcher reads
    ``STATES/loaded_modules_<key>.json``, which ``bokeh_launcher`` writes
    BEFORE any session connects. Under legacy routing that snapshot already
    names the app module, because the launcher itself imported it. Under
    hexagon routing the launcher imports only the SHIM — the legacy module is
    imported here, per session, so the startup snapshot lists neither it nor
    anything it pulls in. Left alone, editing ``standalone_operator.py`` (or a
    visualizer host that mounts no panels) maps to no server and the watcher
    never restarts it: a silent hot-reload hole, and the operator would keep
    serving the old code with nothing logged.

    ``mount_visualizers`` already refreshes for the same reason, but only when
    it mounted at least one panel — which the operator never does. Refreshing
    here covers every hexagon-hosted bokeh process. Best-effort: the helper
    swallows its own errors, because a snapshot failure must not break a
    browser session.
    """
    from helao.helpers.loaded_modules import write_loaded_modules_snapshot

    write_loaded_modules_snapshot(
        os.path.join(wiring.config.root(), "STATES"), server_key
    )
