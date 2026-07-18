"""NativeSyncer (P2c, D2): boundary-clean replacement for legacy
``HelaoSyncer`` (helao/core/drivers/data/sync_driver.py:2059-2093).

``HelaoSyncer`` takes a live HELAO ``Base`` server and reads
``server_cfg``/``world_cfg``/``helaodirs`` off it. ``NativeSyncer`` reads the
same three attributes off the narrow ``SyncerHost`` protocol instead, so this
module never imports ``helao.core.servers.*`` — the whole point of the P2c
native write runtime. It subclasses the verbatim ``SyncDriver`` re-body
(``helao.hexagon.adapters.native.sync_driver``), which owns all pipeline
behavior; only the config-resolution constructor is deliberately rewritten
here (D2).
"""

from typing import Protocol

from helao.core.models.helaodirs import HelaoDirs
from helao.helpers import helao_logging as logging
from helao.hexagon.adapters.native.sync_driver import SyncDriver

__all__ = ["SyncerHost", "NativeSyncer"]

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class SyncerHost(Protocol):
    """Narrow duck-typed host surface ``NativeSyncer`` reads (D2: no Base)."""

    server_cfg: dict
    world_cfg: dict
    helaodirs: HelaoDirs


class NativeSyncer(SyncDriver):
    """Boundary-clean replacement for legacy ``HelaoSyncer`` (D2).

    Replicates HelaoSyncer.__init__'s config resolution
    (helao/core/drivers/data/sync_driver.py:2072-2093) against the
    ``SyncerHost`` protocol: local ``server_cfg['params']`` first, falling
    back to the global ``servers[db_server_name]['params']`` block when the
    local params carry no ``aws_config_path``. The P2e DB shim constructs
    this class; nothing in P2c wires it live.
    """

    def __init__(self, action_serv: SyncerHost, db_server_name: str = "DB"):
        self.host = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
        if (
            not self.config_dict.get("aws_config_path", False)
            and db_server_name in self.world_config["servers"]
        ):
            self.config_dict = self.world_config["servers"][db_server_name].get(
                "params", {}
            )
        LOGGER.info("initializing SyncDriver")
        super().__init__(self.config_dict, self.host.helaodirs)
