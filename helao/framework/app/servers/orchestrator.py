# helao/framework/app/servers/orchestrator.py
"""Deployment-agnostic framework orchestrator entry point.

Builds the framework orchestrator FastAPI app from the loaded CONFIG: loads the
experiment/sequence libraries and derives the action-server list for the
SP-ORCH-4 status heartbeat.

SP-ORCH-5 Part (a) — real transport wiring
------------------------------------------
When CONFIG contains a non-empty ``servers`` map, production startup wires
``HttpTransport(use_rpc=True)`` so the orchestrator dispatches over real
ZMQ-RPC (with HTTP fallback) to action servers.  The full ``servers`` map
(including the orchestrator's own entry) is passed as ``servers_map`` so
:func:`_dispatch_target_for` can resolve host/port from config rather than
falling back to the hardcoded MachineModel or 8000 defaults.

``FakeTransport`` remains the default when no transport is passed (factory
unchanged), so unit tests and in-process runners are unaffected.
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

    # Full servers map (all groups) — used for config-driven target resolution
    # including ORCH self-dispatch.
    servers_map = dict(cfg.get("servers") or {})

    # Heartbeat subset: action-group servers only.
    action_servers = {
        k: v for k, v in servers_map.items()
        if isinstance(v, dict) and v.get("group") == "action"
    }

    # SP-ORCH-5 Part (a2): wire HttpTransport(use_rpc=True) in production when
    # CONFIG provides a non-empty servers map. FakeTransport is the fallback
    # (factory default) when servers_map is empty (no real deployment config).
    # SP-ORCH-5 Part (b2): when a real transport is wired, disable synthesized
    # completion so the loop waits for genuine finished status from the
    # /ws_status subscriber instead of immediately marking actions done.
    transport = None
    synthesize_completion = True  # default: preserve FakeTransport / in-process behaviour
    if servers_map:
        from helao.framework.adapters.http_transport import HttpTransport
        transport = HttpTransport(use_rpc=True)
        synthesize_completion = False  # real transport: wait for real status
        LOGGER.info(
            "orchestrator '%s': wiring HttpTransport(use_rpc=True) "
            "with %d config servers; synthesize_completion=False",
            server_key, len(servers_map)
        )

    return _make_framework_app(
        server_key,
        group="orchestrator",
        transport=transport,
        sequence_lib=sequence_lib,
        experiment_lib=experiment_lib,
        action_servers=action_servers,
        servers_map=servers_map,
        synthesize_completion=synthesize_completion,
    )
