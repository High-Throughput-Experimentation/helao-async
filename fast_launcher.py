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
    if logging.LOGGER is None:
        logging.LOGGER = logging.make_logger(logger_name=server_key, log_dir=log_root)
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
        {},
        "fast_launcher",
        f" ---- starting  {server_key} ----",
        log_dir=log_root,
        info=True,
    )
    fastapp = uvicorn.run(app, host=S["host"], port=S["port"], log_level="warning")
