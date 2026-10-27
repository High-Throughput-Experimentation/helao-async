"""
This script launches a Bokeh server application based on the provided configuration.

Global Variables:
    LOGGER: Global logger instance.
    CONFIG: Global configuration dictionary.

Usage:
    python bokeh_launcher.py <config_file> <server_key>

Arguments:
    config_file: Path to the configuration file.
    server_key: Key to identify the server configuration in the config file.

Modules:
    sys: Provides access to some variables used or maintained by the interpreter.
    os: Provides a way of using operating system dependent functionality.
    functools.partial: Allows partial function application.
    importlib.import_module: Imports a module programmatically.
    bokeh.server.server.Server: Bokeh server class to create and manage Bokeh applications.
    colorama: Cross-platform colored terminal text.
    helao.helpers.print_message: Custom print message function.
    helao.helpers.logging: Custom logging utilities.
    helao.helpers.config_loader: Configuration loader utility.

Functions:
    makeApp: Function to create a Bokeh application, imported dynamically based on the server configuration.

Execution:
    - Initializes colorama for colored terminal output.
    - Loads the configuration file.
    - Sets up logging based on the configuration.
    - Imports the Bokeh application creation function dynamically.
    - Starts the Bokeh server with the specified host, port, and application.
    - Optionally launches a browser to display the Bokeh application.
"""

__all__ = []

import asyncio
import os
import sys
from functools import partial
from importlib import import_module

from bokeh.server.server import Server

# pyzmq's zmq.asyncio (helao.core.rpc.zmq_rpc) requires the add_reader event-loop
# family, which the Windows Proactor loop (the default on Windows) does not
# provide. Install a selector loop as the current event loop before Bokeh/tornado
# creates its IOLoop (which wraps asyncio.get_event_loop()), so any co-located ZMQ
# RPC socket works without the RuntimeWarning and the extra selector thread. This
# replaces asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy()), both
# deprecated as of Python 3.14; asyncio.set_event_loop / SelectorEventLoop are the
# non-deprecated equivalents (SelectorEventLoop is exactly the loop that policy
# built). Safe here: helao uses no asyncio subprocesses, and tornado prefers the
# selector loop on Windows.
if sys.platform == "win32":
    asyncio.set_event_loop(asyncio.SelectorEventLoop())
# The server key names this process in every log record, including the ones
# module-level loggers emit while the imports below run (helao_logging reads it
# at import); children, e.g. the Reflex backend, inherit it. Must stay above
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

    servHost = server_config["host"]
    servPort = server_config["port"]
    servPy = server_config["bokeh"]
    launch_browser = server_config.get("params", {}).get("launch_browser", False)

    config_path = CONFIG["loaded_config_path"]
    # `app_deployment` is where the bokeh app module physically lives; it may
    # differ from the config's own deployment when a generic app (e.g.
    # action_visualizer / live_visualizer) is reused across deployments.
    app_deployment = resolve_app_deployment(server_config, servPy, config_path, LOGGER)
    # CONFIG["deployment"] tracks the config's own deployment so generic
    # visualizers resolve per-server vis modules starting from the right place.
    CONFIG["deployment"] = server_config.get(
        "deployment",
        os.path.basename(os.path.dirname(os.path.dirname(config_path))),
    )
    CONFIG["hlo_version"] = hlo_version
    deploy_git_path = os.path.join(
        helao_repo_root, "helao", "deploy", CONFIG["deployment"], ".git"
    )
    deploy_worktree_path = os.path.dirname(deploy_git_path)
    if os.path.exists(deploy_git_path):
        CONFIG["deployment_version"] = get_hlo_version(deploy_worktree_path)
    else:
        CONFIG["deployment_version"] = hlo_version

    makeApp = import_module(
        f"helao.deploy.{app_deployment}.servers.{server_config['group']}.{server_config['bokeh']}"
    ).makeBokehApp
    root = CONFIG.get("root", None)
    if root is not None:
        log_root = os.path.join(root, "LOGS")
    else:
        log_root = None

    # Hot-reload support: snapshot the modules this bokeh process imported so the
    # launcher's watcher can map a changed file to this server. Bokeh apps expose
    # no HTTP route, so unlike FastAPI servers (which serve /loaded_modules live)
    # we persist a startup snapshot here. Refreshed on every (re)launch.
    if root is not None:
        from helao.helpers.loaded_modules import write_loaded_modules_snapshot

        snap_path = write_loaded_modules_snapshot(
            os.path.join(root, "STATES"), server_key
        )
        if snap_path is not None:
            LOGGER.info(f"wrote loaded-modules snapshot: {snap_path}")
        else:
            LOGGER.warning("failed to write loaded-modules snapshot")

    LOGGER.info(f" ---- starting  {server_key} ----")

    bokehapp = Server(
        {
            f"/{servPy}": partial(
                makeApp,
                confPrefix=confArg,
                server_key=server_key,
                helao_repo_root=helao_repo_root,
            )
        },
        port=servPort,
        address=servHost,
        allow_websocket_origin=[f"{servHost}:{servPort}"],
    )
    LOGGER.info(f"started {server_key} {bokehapp}")
    bokehapp.start()
    if launch_browser:
        bokehapp.io_loop.add_callback(bokehapp.show, f"/{servPy}")
    bokehapp.io_loop.start()
