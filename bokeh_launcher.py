__all__ = []

import sys
import os
from functools import partial
from importlib import import_module
from bokeh.server.server import Server
import colorama
from helao.helpers.print_message import print_message
from helao.helpers import logging
from helao.helpers import config_loader

global logger
global global_config


if __name__ == "__main__":
    log_root = "."
    colorama.init(strip=not sys.stdout.isatty())  # strip colors if stdout is redirected
    helao_root = os.path.dirname(os.path.realpath(__file__))
    server_key = sys.argv[2]
    confArg = sys.argv[1]
    config = config_loader.config_loader(confArg, helao_root)
    log_root = os.path.join(config["root"], "LOGS") if "root" in config else None
    if logging.LOGGER is None:
        logging.LOGGER = logging.make_logger(logger_name=server_key, log_dir=log_root)
    logger = logging.LOGGER
    if config_loader.CONFIG is None:
        config_loader.CONFIG = config
    C = config["servers"]
    S = C[server_key]
    servHost = S["host"]
    servPort = S["port"]
    servPy = S["bokeh"]
    launch_browser = S.get("params", {}).get("launch_browser", False)

    makeApp = import_module(f"helao.servers.{S['group']}.{S['bokeh']}").makeBokehApp
    root = config.get("root", None)
    if root is not None:
        log_root = os.path.join(root, "LOGS")
    else:
        log_root = None
    print_message(
        {},
        "bokeh_launcher",
        f" ---- starting  {server_key} ----",
        log_dir=log_root,
        info=True,
    )

    bokehapp = Server(
        {
            f"/{servPy}": partial(
                makeApp,
                confPrefix=confArg,
                server_key=server_key,
                helao_root=helao_root,
            )
        },
        port=servPort,
        address=servHost,
        allow_websocket_origin=[f"{servHost}:{servPort}"],
    )
    print_message(
        {},
        "bokeh_launcher",
        f"started {server_key} {bokehapp}",
        log_dir=log_root,
        info=True,
    )
    bokehapp.start()
    if launch_browser:
        bokehapp.io_loop.add_callback(bokehapp.show, f"/{servPy}")
    bokehapp.io_loop.start()
