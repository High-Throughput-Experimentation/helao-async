"""Hexagon composition root (spec §4.5).

The ONLY layer that constructs FastAPI objects and wires adapters into
ports. Fail loud (F2b): build_wiring raises without an installed CONFIG;
each makeApp requires its composition's consumed port set BEFORE building
the app — a missing adapter aborts startup, never a silent fake. The
co-located RPC mirror (spec §7.1) is inherited from legacy HelaoFastAPI's
startup hook (ROUTER on http_port+10000, configured-host bind with 0.0.0.0
fallback). Launcher routing: helao/deploy/hexagon/ shim modules call these
factories via the per-server `deployment: hexagon` config key — zero
launcher edits, per-config atomic cut-over/rollback."""

import os
from importlib import import_module

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
    ORCH_REQUIRED,
    VIS_REQUIRED,
    PortWiring,
)

__all__ = ["build_wiring", "makeActionApp", "makeOrchApp", "makeVisApp"]


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
        # P2b-1 native write runtime (base bound later by the active graft)
        artifact_store=NativeArtifactStoreAdapter(config=config, clock=clock),
        data_sink=NativeDataSinkAdapter(),
    )


def makeOrchApp(server_key: str):
    from helao.core.servers.orch_api import OrchAPI
    from helao.hexagon.app.dispatch_loop import graft_hexagon_loop

    wiring = build_wiring(server_key)
    wiring.require(*ORCH_REQUIRED)

    app = OrchAPI(
        server_key,
        server_key,
        "Hexagon-composed orchestrator (wrapped legacy Orch + reducer loop)",
        version=3.0,
        driver_classes=None,
    )
    app.hexagon_wiring = wiring  # type: ignore[attr-defined]
    app.hexagon_graft = None  # type: ignore[attr-defined]

    # Registered AFTER OrchAPI.__init__'s own startup handler, so it runs
    # AFTER `self.orch = Orch(fastapp=self)` + myinit (Starlette preserves
    # registration order): the graft sees the live legacy Orch.
    @app.on_event("startup")
    async def _hexagon_graft_startup():
        app.hexagon_graft = graft_hexagon_loop(app.orch, wiring)  # type: ignore[attr-defined]

    @app.on_event("shutdown")
    async def _hexagon_graft_shutdown():
        if app.hexagon_graft is not None:  # type: ignore[attr-defined]
            await app.hexagon_graft.close()  # type: ignore[attr-defined]

    return app


def makeActionApp(server_key: str, legacy_module: str):
    from helao.hexagon.app.active_graft import graft_active_write_path

    wiring = build_wiring(server_key)
    wiring.require(*ACTION_REQUIRED)
    app = import_module(legacy_module).makeApp(server_key)
    app.hexagon_wiring = wiring
    app.hexagon_active_graft = None
    app.hexagon_ws_bridge = None

    # Registered AFTER the legacy BaseAPI's own startup handler (which sets
    # self.base = Base(app=self, ...), base_api.py:646; Starlette preserves
    # registration order): the graft sees the live app.base and rebinds
    # contain_action + meta_writer before any action can be contained.
    @app.on_event("startup")
    async def _hexagon_active_graft_startup():
        app.hexagon_active_graft = graft_active_write_path(app.base, wiring)
        # P2b-2 (D3): the WS publish bridge needs the live Base's fan-out
        # queues — construct and bind it now, ACTION apps only (orch WS
        # stays on legacy relays, Q1: makeOrchApp never binds).
        if not isinstance(wiring.status, DispatcherStatusAdapter):
            raise UnwiredPortError(
                "WS publish bridge requires DispatcherStatusAdapter status wiring"
            )
        status_adapter = wiring.status
        bridge = WsPublishBridge(app.base.status_q, app.base.data_q, app.base.live_q)
        status_adapter.bind_publish_bridge(bridge)
        app.hexagon_ws_bridge = bridge

    @app.on_event("shutdown")
    async def _hexagon_active_graft_shutdown():
        if app.hexagon_active_graft is not None:
            app.hexagon_active_graft.close()

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
