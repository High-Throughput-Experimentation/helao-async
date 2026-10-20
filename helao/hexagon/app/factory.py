"""Composition root: builds the port wiring every host consumes.
`ActionHost.__init__` (and `OrchHost` through it) calls `build_wiring` when no
wiring is injected; fail-loud: it raises without an installed CONFIG."""

import os

from helao.helpers import helao_logging as logging
from helao.hexagon.adapters.shared.clock import LegacyClockAdapter
from helao.hexagon.adapters.shared.config import from_global_config
from helao.hexagon.adapters.shared.health import LegacyHealthAdapter
from helao.hexagon.adapters.shared.logging_adapter import LegacyLoggingAdapter
from helao.hexagon.adapters.shared.state_persistence import QueuePckStore
from helao.hexagon.adapters.shared.status import DispatcherStatusAdapter
from helao.hexagon.adapters.shared.transport import LegacyTransportAdapter
from helao.hexagon.adapters.native.artifact_store import NativeArtifactStoreAdapter
from helao.hexagon.app.wiring import PortWiring

__all__ = ["build_wiring"]

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


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
    )
