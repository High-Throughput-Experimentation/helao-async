
__all__ = []

import sys
import os
from importlib import import_module
from functools import partial

from bokeh.server.server import Server

from helaocore.helper.print_message import print_message


confPrefix = sys.argv[1]
servKey = sys.argv[2]
config = import_module(f"helao.config.{confPrefix}").config
C = config["servers"]
S = C[servKey]
servHost = S["host"]
servPort = S["port"]
servPy = S["bokeh"]

makeApp = import_module(f"helao.library.server.{S['group']}.{S['bokeh']}").makeBokehApp
root =  config.get("root", None)
if root is not None:
    log_root = os.path.join(root, "LOGS")
else:
    log_root = None


if __name__ == "__main__":
    print_message({}, "bokeh_launcher", f" ---- starting  {servKey} ----",
                  log_dir = log_root,
                  info = True)

    bokehapp = Server(
                      {f"/{servPy}": partial(makeApp, confPrefix=confPrefix, servKey=servKey)}, 
                      port=servPort, 
                      address=servHost, 
                      allow_websocket_origin=[f"{servHost}:{servPort}"]
                      )
    print_message({}, "bokeh_launcher", f"started {servKey} {bokehapp}",
                      log_dir = log_root,
                      info = True)
    bokehapp.start()
    bokehapp.io_loop.add_callback(bokehapp.show, f"/{servPy}")
    bokehapp.io_loop.start()
