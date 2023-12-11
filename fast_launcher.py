__all__ = []

import traceback
import sys
import os
from importlib import import_module
from uvicorn.config import LOGGING_CONFIG
import uvicorn
import colorama

from helao.helpers.print_message import print_message
from helao.helpers.config_loader import config_loader


if __name__ == "__main__":
    try:
        colorama.init(strip=not sys.stdout.isatty())  # strip colors if stdout is redirected
        helao_root = os.path.dirname(os.path.realpath(__file__))
        server_key = sys.argv[2]
        confArg = sys.argv[1]
        config = config_loader(confArg, helao_root)
        C = config["servers"]
        S = C[server_key]

        makeApp = import_module(f"helao.servers.{S['group']}.{S['fast']}").makeApp
        app = makeApp(confArg, server_key, helao_root)
        root = config.get("root", None)
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
        fastapp = uvicorn.run(app, host=S["host"], port=S["port"])
    except Exception as e:
        tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        print_message(
            {},
            "fast_launcher",
            f"fast_launcher unhandled exception: {repr(e), tb,}",
            log_dir=log_root,
            error=True
        )