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
from importlib import import_module
from uvicorn.config import LOGGING_CONFIG
import uvicorn
import colorama


from helao.helpers import helao_logging as logging
from helao.helpers import config_loader
from helao.helpers.yml_tools import yml_load


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

    makeApp = import_module(
        f"helao.servers.{server_config['group']}.{server_config['fast']}"
    ).makeApp
    app = makeApp(server_key)
    root = CONFIG.get("root", None)
    if root is not None:
        log_root = os.path.join(root, "LOGS")
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
