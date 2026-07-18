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
from helao.hexagon.app.wiring import ACTION_REQUIRED, ORCH_REQUIRED, PortWiring

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
    """P2d compat-facade (D1/D2): host a legacy Bokeh app UNMODIFIED.

    Delegates completely to the legacy module's makeBokehApp — no wiring is
    attached because HelaoBokehAPI self-configures from config_loader.CONFIG
    (server_api.py) and exposes no injection seam. Native vis hosting
    (ConfigPort/WsSubscriber adapters) is P3; this only makes the bokeh
    PROCESS launchable under `deployment: hexagon` routing.
    """
    return import_module(legacy_module).makeBokehApp(
        doc, confPrefix, server_key, helao_repo_root
    )
