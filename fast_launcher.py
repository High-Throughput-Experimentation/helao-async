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
from importlib import import_module

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

# The server key names this process in every log record, including the ones
# module-level loggers emit while the imports below run (helao_logging reads it
# at import); every subprocess this server spawns inherits it. Must stay above
# the first helao import.
if __name__ == "__main__" and len(sys.argv) > 2:
    os.environ["HELAO_SERVER_KEY"] = sys.argv[2]

from helao.core.version import get_hlo_version, hlo_version
from helao.helpers.launcher_bootstrap import (
    init_colorama,
    launcher_bootstrap,
    resolve_app_deployment,
)
from helao.helpers.parent_death import arm_parent_death_signal

if __name__ == "__main__":
    # Die with launch.py rather than orphaning and holding this server's port if
    # the launcher is SIGKILLed. Linux-only and a no-op elsewhere; must run
    # before anything binds a port, and from the child rather than a
    # preexec_fn (see helao.helpers.parent_death).
    arm_parent_death_signal()
    init_colorama()
    helao_repo_root = os.path.dirname(os.path.realpath(__file__))
    server_key = sys.argv[2]
    confArg = sys.argv[1]
    CONFIG, server_config, LOGGER = launcher_bootstrap(confArg, server_key)
    deployment = resolve_app_deployment(
        server_config,
        server_config["fast"],
        CONFIG["loaded_config_path"],
        LOGGER,
    )
    CONFIG["deployment"] = deployment
    CONFIG["hlo_version"] = hlo_version
    deploy_git_path = os.path.join(
        helao_repo_root, "helao", "deploy", CONFIG["deployment"], ".git"
    )
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
