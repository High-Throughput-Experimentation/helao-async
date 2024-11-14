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


from helao.helpers.print_message import print_message
from helao.helpers import logging
from helao.helpers import config_loader
from helao.helpers.yml_tools import yml_load

global LOGGER
global CONFIG


if __name__ == "__main__":
    log_root = "."
    colorama.init(strip=not sys.stdout.isatty())  # strip colors if stdout is redirected
    helao_root = os.path.dirname(os.path.realpath(__file__))
    server_key = sys.argv[2]
    confArg = sys.argv[1]
    CONFIG = config_loader.config_loader(confArg, helao_root)
    log_root = os.path.join(CONFIG["root"], "LOGS") if "root" in CONFIG else None
    if CONFIG.get("alert_config_path", False):
        email_config = yml_load(CONFIG["alert_config_path"])
    else:
        email_config = {}
    if logging.LOGGER is None:
        logging.LOGGER = logging.make_logger(
            logger_name=server_key, log_dir=log_root, email_config=email_config
        )
    LOGGER = logging.LOGGER
    if config_loader.CONFIG is None:
        config_loader.CONFIG = CONFIG
    C = CONFIG["servers"]
    S = C[server_key]

    makeApp = import_module(f"helao.servers.{S['group']}.{S['fast']}").makeApp
    app = makeApp(confArg, server_key, helao_root)
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

    print_message(
        LOGGER,
        "fast_launcher",
        f" ---- starting  {server_key} ----",
        log_dir=log_root,
        info=True,
    )
    fastapp = uvicorn.run(app, host=S["host"], port=S["port"], log_level="warning")
