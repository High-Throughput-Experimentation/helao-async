# helao/framework/app/servers/orchestrator.py
"""Deployment-agnostic framework orchestrator entry point.

Builds the framework orchestrator FastAPI app from the loaded CONFIG: loads the
experiment/sequence libraries and derives the action-server list for the
SP-ORCH-4 status heartbeat.
"""
__all__ = ["makeApp"]

from helao.framework.support import config_loader
from helao.framework.support import helao_logging as logging
from helao.framework.app.factory import makeApp as _make_framework_app

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def makeApp(server_key):
    """Construct the framework orchestrator app for ``server_key`` from CONFIG."""
    cfg = config_loader.CONFIG
    sequence_lib = {}
    experiment_lib = {}
    # Only autoload when libraries are actually configured. A configured-but-failing
    # library is a real startup error and MUST propagate loudly (a silently empty
    # orchestrator can run nothing); an UNconfigured deployment legitimately has none
    # (and the unit test omits the keys, so import_autolibs is never called there).
    from helao.helpers.import_autolibs import import_autolibs
    # Real signature: import_autolibs(world_config_dict, lib_dir=None,
    #                                 user_lib_dir=None, lib_type="sequence");
    # lib_type selects "experiment_libraries" vs "sequence_libraries" in the config.
    if cfg.get("experiment_libraries"):
        experiment_lib, _, _ = import_autolibs(cfg, lib_type="experiment")
    if cfg.get("sequence_libraries"):
        sequence_lib, _, _ = import_autolibs(cfg, lib_type="sequence")
    action_servers = {
        k: v for k, v in (cfg.get("servers") or {}).items()
        if isinstance(v, dict) and v.get("group") == "action"
    }
    return _make_framework_app(
        server_key,
        group="orchestrator",
        sequence_lib=sequence_lib,
        experiment_lib=experiment_lib,
        action_servers=action_servers,
    )
