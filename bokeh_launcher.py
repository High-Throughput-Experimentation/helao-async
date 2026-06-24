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

import sys
import os
from glob import glob
from functools import partial
from importlib import import_module
from bokeh.server.server import Server
import colorama
from helao.helpers import helao_logging as logging
from helao.helpers import config_loader
from helao.helpers.yml_tools import yml_load


def resolve_app_module_path(deployment: str, group: str, name: str) -> str:
    """Resolve the app module import path. ``deployment == "framework"`` selects the
    deployment-agnostic framework app under ``helao.framework.app.servers``; any
    other value uses the per-deployment path (unchanged default)."""
    if deployment == "framework":
        return f"helao.framework.app.servers.{name}"
    return f"helao.deploy.{deployment}.servers.{group}.{name}"


def bridge_framework_config() -> None:
    """Point the framework config global at the launcher-loaded legacy CONFIG so
    framework apps (HelaoVis, orchestrator entry, operator backend autoload) see it."""
    from helao.helpers import config_loader as _legacy
    from helao.framework.support import config_loader as _fw
    _fw.CONFIG = _legacy.CONFIG


if __name__ == "__main__":
    log_root = "."
    colorama.init(strip=not sys.stdout.isatty())  # strip colors if stdout is redirected
    helao_repo_root = os.path.dirname(os.path.realpath(__file__))
    server_key = sys.argv[2]
    confArg = sys.argv[1]
    if config_loader.CONFIG is None:
        config_loader.CONFIG = config_loader.load_global_config(confArg, True)
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
        possible_deployments = glob(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(config_path))),
                "*",
                "servers",
                server_config["group"],
                f"{server_config['bokeh']}.py",
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
            # prefer detected deployment
            filter_possible = [
                x
                for x in possible_deployments
                if x.startswith(os.path.dirname(os.path.dirname(config_path)))
            ][0]
            app_deployment = os.path.basename(
                os.path.dirname(os.path.dirname(os.path.dirname(filter_possible)))
            )
            LOGGER.info(
                f"Auto-detected deployment from multiple options: {app_deployment}"
            )
        else:
            raise FileNotFoundError(
                f"Could not find deployment for {server_config['bokeh']} in {server_config['group']}"
            )
    # CONFIG["deployment"] tracks the config's own deployment so generic
    # visualizers resolve per-server vis modules starting from the right place.
    # For framework apps, keep the detected deployment so per-instrument vis
    # modules resolve from the real deployment.
    if app_deployment == "framework":
        CONFIG["deployment"] = detected_deployment
    else:
        CONFIG["deployment"] = server_config.get("deployment", detected_deployment)
    bridge_framework_config()
    makeApp = import_module(
        resolve_app_module_path(app_deployment, server_config["group"], server_config["bokeh"])
    ).makeBokehApp
    root = CONFIG.get("root", None)
    if root is not None:
        log_root = os.path.join(root, "LOGS")
    else:
        log_root = None
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
