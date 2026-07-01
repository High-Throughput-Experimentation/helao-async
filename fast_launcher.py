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

import sys
import os
from glob import glob
from importlib import import_module
from uvicorn.config import LOGGING_CONFIG
import uvicorn
import colorama


from helao.helpers import helao_logging as logging
from helao.framework.support import helao_logging as fw_logging
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
    # Framework servers write per-server logs to <root>/LOGS_FW/<server_key>.log
    # (parallel to the legacy LOGS). After the migration completes, retire LOGS
    # and rename LOGS_FW -> LOGS.
    log_root = os.path.join(CONFIG["root"], "LOGS_FW") if "root" in CONFIG else None
    if log_root is not None:
        os.makedirs(log_root, exist_ok=True)
    if CONFIG.get("alert_config_path", False):
        email_config = yml_load(CONFIG["alert_config_path"])
    else:
        email_config = {}
    # Build the per-server logger via the FRAMEWORK logging module (framework
    # code reads helao.framework.support.helao_logging.LOGGER, a different global
    # than the legacy helao.helpers one), then point BOTH module globals at the
    # same stdlib logger (getLogger(server_key)) so every module — framework or
    # legacy-helper — logs to the single LOGS_FW/<server_key>.log file.
    if fw_logging.LOGGER is None:
        fw_logging.LOGGER = fw_logging.make_logger(
            logger_name=server_key,
            log_dir=log_root,
            email_config=email_config,
            log_level=server_config.get("log_level", CONFIG.get("log_level", 20)),
        )
    logging.LOGGER = fw_logging.LOGGER
    LOGGER = fw_logging.LOGGER
    LOGGER.info(f"Loaded config from: {CONFIG['loaded_config_path']}")

    config_path = CONFIG["loaded_config_path"]
    detected_deployment = os.path.basename(
        os.path.dirname(os.path.dirname(config_path))
    )
    deployment = server_config.get("deployment", detected_deployment)
    if "deployment" not in server_config:
        possible_deployments = glob(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(config_path))),
                "*",
                "servers",
                server_config["group"],
                f"{server_config['fast']}.py",
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
            # prefer detected deployment
            filter_possible = [
                x
                for x in possible_deployments
                if x.startswith(os.path.dirname(os.path.dirname(config_path)))
            ][0]
            deployment = os.path.basename(
                os.path.dirname(os.path.dirname(os.path.dirname(filter_possible)))
            )
            LOGGER.info(f"Auto-detected deployment from multiple options: {deployment}")
        else:
            raise FileNotFoundError(
                f"Could not find deployment for {server_config['fast']} in {server_config['group']}"
            )
    CONFIG["deployment"] = deployment
    bridge_framework_config()
    makeApp = import_module(
        resolve_app_module_path(deployment, server_config["group"], server_config["fast"])
    ).makeApp
    app = makeApp(server_key)
    root = CONFIG.get("root", None)
    if root is not None:
        log_root = os.path.join(root, "LOGS_FW")
    else:
        log_root = None
    # LOGGING_CONFIG["formatters"]["default"]["fmt"] = "%(asctime)s [%(name)s] %(levelprefix)s %(message)s"

    LOGGING_CONFIG["formatters"]["default"]["datefmt"] = "%H:%M:%S"
    LOGGING_CONFIG["formatters"]["default"][
        "fmt"
    ] = f"\n[%(asctime)s_{server_key}]: %(levelprefix)s %(message)s\r"
    LOGGING_CONFIG["formatters"]["default"]["use_colors"] = False

    LOGGING_CONFIG["formatters"]["access"]["datefmt"] = "%H:%M:%S"
    LOGGING_CONFIG["formatters"]["access"][
        "fmt"
    ] = f"\n[%(asctime)s_{server_key}]: %(levelprefix)s %(message)s\r"
    LOGGING_CONFIG["formatters"]["access"]["use_colors"] = False

    LOGGER.info(f" ---- starting  {server_key} ----")
    fastapp = uvicorn.run(
        app,
        host=server_config["host"],
        port=server_config["port"],
        log_level="warning",
        timeout_graceful_shutdown=5,
    )
