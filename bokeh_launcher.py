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
from glob import glob
from importlib import import_module

import colorama
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
from helao.helpers import config_loader
from helao.helpers import helao_logging as logging
from helao.helpers.yml_tools import yml_load

if __name__ == "__main__":
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

    servHost = server_config["host"]
    servPort = server_config["port"]
    servPy = server_config["bokeh"]
    launch_browser = server_config.get("params", {}).get("launch_browser", False)

    config_path = CONFIG["loaded_config_path"]
    detected_deployment = os.path.basename(
        os.path.dirname(os.path.dirname(config_path))
    )
    # `app_deployment` is where the bokeh app module physically lives; it may
    # differ from the config's own deployment when a generic app (e.g.
    # action_visualizer / live_visualizer) is reused across deployments.
    app_deployment = server_config.get("deployment", detected_deployment)
    if "deployment" not in server_config:
        possible_deployments = sorted(
            glob(
                os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(config_path))),
                    "*",
                    "servers",
                    server_config["group"],
                    f"{server_config['bokeh']}.py",
                )
            )
        )
        if len(possible_deployments) == 1:
            app_deployment = os.path.basename(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(possible_deployments[0]))
                )
            )
            LOGGER.info(f"Auto-detected deployment: {app_deployment}")
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
            app_deployment = os.path.basename(
                os.path.dirname(os.path.dirname(os.path.dirname(chosen)))
            )
            if filter_possible:
                LOGGER.info(
                    f"Auto-detected deployment from multiple options: {app_deployment}"
                )
            else:
                LOGGER.warning(
                    f"No deployment under the config path matched "
                    f"{server_config['bokeh']} in {server_config['group']}; "
                    f"falling back to '{app_deployment}'. Set an explicit "
                    f"'deployment:' key on this server to disambiguate."
                )
        else:
            raise FileNotFoundError(
                f"Could not find deployment for {server_config['bokeh']} in {server_config['group']}"
            )
    # CONFIG["deployment"] tracks the config's own deployment so generic
    # visualizers resolve per-server vis modules starting from the right place.
    CONFIG["deployment"] = server_config.get("deployment", detected_deployment)

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
