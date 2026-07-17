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

from helao.hexagon.adapters.errors import HexagonDeferred
from helao.hexagon.adapters.legacy.clock import LegacyClockAdapter
from helao.hexagon.adapters.legacy.config import from_global_config
from helao.hexagon.adapters.legacy.logging_adapter import LegacyLoggingAdapter
from helao.hexagon.adapters.legacy.state_persistence import QueuePckStore
from helao.hexagon.adapters.legacy.transport import LegacyTransportAdapter
from helao.hexagon.app.wiring import ACTION_REQUIRED, ORCH_REQUIRED, PortWiring

__all__ = ["build_wiring", "makeActionApp", "makeOrchApp", "makeVisApp"]


def build_wiring(server_key: str) -> PortWiring:
    config = from_global_config()  # raises when CONFIG is not installed
    root = config.root()  # KeyError -> loud, like helao_dirs
    log_root = os.path.join(root, "LOGS")
    return PortWiring(
        config=config,
        logging=LegacyLoggingAdapter(),
        clock=LegacyClockAdapter.from_offset_file(log_root),
        transport=LegacyTransportAdapter(config),
        state_persistence=QueuePckStore(root),
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
    wiring = build_wiring(server_key)
    wiring.require(*ACTION_REQUIRED)
    app = import_module(legacy_module).makeApp(server_key)
    app.hexagon_wiring = wiring
    return app


def makeVisApp(*args, **kwargs):
    raise HexagonDeferred(
        "visualizer/operator hosting via hexagon vis adapters is P2 "
        "(master spec §12); keep bokeh entries on their legacy deployment"
    )
