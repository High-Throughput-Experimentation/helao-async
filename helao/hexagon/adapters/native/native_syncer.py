"""NativeSyncer (P2c, D2): the syncer the orchestrator, the SYNC server and the
sim DB server construct, reached through ``SyncPort``.

It reads ``server_cfg``/``world_cfg``/``helaodirs`` off the narrow
``SyncerHost`` protocol, so this module never imports ``helao.core.servers.*``.
It subclasses ``SyncDriver`` (``helao.hexagon.adapters.native.sync_driver``),
which owns all pipeline behavior; only the config-resolution constructor lives
here (D2).
"""

from typing import Optional, Protocol

from helao.core.models.helaodirs import HelaoDirs
from helao.helpers import helao_logging as logging
from helao.helpers.server_keys import resolve_sync_server_key
from helao.hexagon.adapters.native.sync_driver import SyncDriver

__all__ = ["SyncerHost", "NativeSyncer"]

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class SyncerHost(Protocol):
    """Narrow duck-typed host surface ``NativeSyncer`` reads (D2: no Base)."""

    server_cfg: dict
    world_cfg: dict
    helaodirs: HelaoDirs


class NativeSyncer(SyncDriver):
    """Boundary-clean syncer: config resolution against ``SyncerHost`` (D2).

    Local ``server_cfg['params']`` first, falling back to the global
    ``servers[sync_server_name]['params']`` block when the local params carry
    no ``aws_config_path``. Constructed at startup (its ``__init__`` needs a
    running loop) by the orchestrator, the SYNC server and the sim DB server.
    """

    def __init__(self, action_serv: SyncerHost, sync_server_name: Optional[str] = None):
        self.host = action_serv
        entry = action_serv.server_cfg
        self.config_dict = entry.get("params", {})
        self.world_config = action_serv.world_cfg
        resolved_key = resolve_sync_server_key(
            self.world_config, preferred=sync_server_name
        )
        if not self.config_dict.get("aws_config_path", False) and resolved_key:
            entry = self.world_config["servers"][resolved_key]
            self.config_dict = entry.get("params", {})
        LOGGER.info("initializing SyncDriver")
        super().__init__(
            self.config_dict,
            self.host.helaodirs,
            postfinish_hooks=entry.get("postfinish_hooks"),
        )
