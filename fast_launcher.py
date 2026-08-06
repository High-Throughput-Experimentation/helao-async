"""
This script is the entry point for launching a Helao server using Uvicorn.

Modules:
    sys: Provides access to some variables used or maintained by the interpreter.
    os: Provides a way of using operating system dependent functionality.
    importlib: Provides the implementation of the import statement.
    uvicorn.config: Provides configuration for Uvicorn.
    uvicorn: ASGI server for Python.
    colorama: Cross-platform colored terminal text.
    helao.helpers.print_message: Custom print message helper.
    helao.helpers.logging: Custom logging helper.
    helao.helpers.config_loader: Custom configuration loader.

Global Variables:
    LOGGER: Global logger instance.
    CONFIG: Global configuration dictionary.

Functions:
    main: The main function that initializes and starts the Uvicorn server.

Usage:
    This script is intended to be run as a standalone script. It requires two command-line arguments:
    1. Configuration argument (confArg)
    2. Server key (server_key)

    Example:
        python fast_launcher.py <confArg> <server_key>
"""

__all__ = []

import asyncio
import os
import sys
from glob import glob
from importlib import import_module

import colorama
import uvicorn
from uvicorn.config import LOGGING_CONFIG

# pyzmq's zmq.asyncio (helao.core.rpc.zmq_rpc) requires the add_reader event-loop
# family, which the Windows Proactor loop (the default on Windows) does not
# provide. On Windows we force a selector loop via ``loop_factory`` on the
# ``asyncio.run`` call below (see ``_LOOP_FACTORY``), so the co-located ZMQ RPC
# server works without the RuntimeWarning and the extra tornado selector thread.
# This replaces ``asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())``,
# both of which are deprecated as of Python 3.14. Safe here: helao uses no asyncio
# subprocesses.
_LOOP_FACTORY = asyncio.SelectorEventLoop if sys.platform == "win32" else None


from helao.core.version import get_hlo_version, hlo_version
from helao.helpers import config_loader
from helao.helpers import helao_logging as logging
from helao.helpers.parent_death import arm_parent_death_signal
from helao.helpers.yml_tools import yml_load

if __name__ == "__main__":
    # Die with launch.py rather than orphaning and holding this server's port if
    # the launcher is SIGKILLed. Linux-only and a no-op elsewhere; must run
    # before anything binds a port, and from the child rather than a
    # preexec_fn (see helao.helpers.parent_death).
    arm_parent_death_signal()
    log_root = "."
    # launch.py sets HELAO_FORCE_COLOR when it pumps our output through its own
    # tty stdout: emit raw ANSI so the launcher's colorama translates it (which
    # on Windows must happen against a real console handle, not our pipe),
    # instead of stripping just because our own stdout is a pipe.
    if os.environ.get("HELAO_FORCE_COLOR") == "1":
        colorama.init(strip=False, convert=False)
    else:
        colorama.init(
            strip=not sys.stdout.isatty()
        )  # strip colors if stdout is redirected
    helao_repo_root = os.path.dirname(os.path.realpath(__file__))
    server_key = sys.argv[2]
    confArg = sys.argv[1]
    if config_loader.CONFIG is None:
        config_dict, _validated = config_loader.read_validated_config(confArg)
        config_loader.install_global_config(config_dict)
    CONFIG = config_loader.CONFIG

    all_servers_config = CONFIG["servers"]
    server_config = all_servers_config[server_key]
    log_root = os.path.join(CONFIG["root"], "LOGS") if "root" in CONFIG else None
    if CONFIG.get("alert_config_path", False):
        email_config = yml_load(CONFIG["alert_config_path"])
    else:
        email_config = {}
    if logging.LOGGER is None:
        logging.LOGGER = logging.make_logger(
            logger_name=server_key,
            log_dir=log_root,
            email_config=email_config,
            log_level=server_config.get("log_level", CONFIG.get("log_level", 20)),
        )
    LOGGER = logging.LOGGER
    LOGGER.info(f"Loaded config from: {CONFIG['loaded_config_path']}")

    config_path = CONFIG["loaded_config_path"]
    detected_deployment = os.path.basename(
        os.path.dirname(os.path.dirname(config_path))
    )
    deployment = server_config.get("deployment", detected_deployment)
    if "deployment" not in server_config:
        possible_deployments = sorted(
            glob(
                os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(config_path))),
                    "*",
                    "servers",
                    server_config["group"],
                    f"{server_config['fast']}.py",
                )
            )
        )
        if len(possible_deployments) == 1:
            deployment = os.path.basename(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(possible_deployments[0]))
                )
            )
            LOGGER.info(f"Auto-detected deployment: {deployment}")
        elif len(possible_deployments) > 1:
            # Prefer the deployment matching the config's own path. If none
            # match (e.g. a derived/private config that reuses another
            # deployment's generic app), fall back to the first match and warn
            # rather than crashing on an empty filter.
            config_dep_dir = os.path.dirname(os.path.dirname(config_path))
            filter_possible = [
                x for x in possible_deployments if x.startswith(config_dep_dir)
            ]
            chosen = filter_possible[0] if filter_possible else possible_deployments[0]
            deployment = os.path.basename(
                os.path.dirname(os.path.dirname(os.path.dirname(chosen)))
            )
            if filter_possible:
                LOGGER.info(
                    f"Auto-detected deployment from multiple options: {deployment}"
                )
            else:
                LOGGER.warning(
                    f"No deployment under the config path matched "
                    f"{server_config['fast']} in {server_config['group']}; "
                    f"falling back to '{deployment}'. Set an explicit "
                    f"'deployment:' key on this server to disambiguate."
                )
        else:
            raise FileNotFoundError(
                f"Could not find deployment for {server_config['fast']} in {server_config['group']}"
            )
    CONFIG["deployment"] = deployment
    CONFIG["hlo_version"] = hlo_version
    deploy_git_path = os.path.join(helao_repo_root, "helao", "deploy", CONFIG["deployment"], ".git")
    deploy_worktree_path = os.path.dirname(deploy_git_path)
    if os.path.exists(deploy_git_path):
        CONFIG["deployment_version"] = get_hlo_version(deploy_worktree_path)
    else:
        CONFIG["deployment_version"] = hlo_version

    # Launcher CLI override: `--restore` forces orchestrators to import their
    # saved queues on startup regardless of the config default. server_config is
    # the same dict HelaoFastAPI exposes as server_cfg (CONFIG["servers"][key]),
    # so mutating it here — before makeApp constructs the app — is visible to
    # Orch.myinit's restore gate.
    if "--restore" in sys.argv[3:] and server_config.get("group") == "orchestrator":
        server_config["restore_queues_on_startup"] = True
        LOGGER.info("--restore flag set; orchestrator will import saved queues.")

    makeApp = import_module(
        f"helao.deploy.{deployment}.servers.{server_config['group']}.{server_config['fast']}"
    ).makeApp
    app = makeApp(server_key)
    root = CONFIG.get("root", None)
    if root is not None:
        log_root = os.path.join(root, "LOGS")
    else:
        log_root = None
    # LOGGING_CONFIG["formatters"]["default"]["fmt"] = "%(asctime)s [%(name)s] %(levelprefix)s %(message)s"

    # NB: no leading "\n" / trailing "\r". The old carriage return left the
    # cursor at column 0 without a newline; when multiple server subprocesses
    # interleave on the shared (block-buffered) stdout on Linux, later writes
    # overwrote from column 0, producing variable indentation. A plain line with
    # the handler's default "\n" terminator renders one clean line per record.
    LOGGING_CONFIG["formatters"]["default"]["datefmt"] = "%H:%M:%S"
    LOGGING_CONFIG["formatters"]["default"][
        "fmt"
    ] = f"[%(asctime)s_{server_key}]: %(levelprefix)s %(message)s"
    LOGGING_CONFIG["formatters"]["default"]["use_colors"] = False

    LOGGING_CONFIG["formatters"]["access"]["datefmt"] = "%H:%M:%S"
    LOGGING_CONFIG["formatters"]["access"][
        "fmt"
    ] = f"[%(asctime)s_{server_key}]: %(levelprefix)s %(message)s"
    LOGGING_CONFIG["formatters"]["access"]["use_colors"] = False

    LOGGER.info(f" ---- starting  {server_key} ----")
    # Run uvicorn's server coroutine under asyncio.run() rather than
    # uvicorn.run(). uvicorn.run() -> Server.run() feeds its own loop factory to
    # asyncio (asyncio.ProactorEventLoop on Windows), which is instantiated
    # directly and would ignore our selector requirement. asyncio.run() builds the
    # loop from ``loop_factory`` (``_LOOP_FACTORY``: SelectorEventLoop on Windows,
    # default elsewhere), so the co-located zmq.asyncio RPC server gets the
    # add_reader-capable selector loop it needs. Behavior is unchanged off Windows
    # (loop_factory=None yields uvicorn's usual loop type).
    config = uvicorn.Config(
        app,
        host=server_config["host"],
        port=server_config["port"],
        log_level="warning",
        timeout_graceful_shutdown=5,
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve(), loop_factory=_LOOP_FACTORY)
