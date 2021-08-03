import sys
from importlib import import_module
from functools import partial

from bokeh.server.server import Server


confPrefix = sys.argv[1]
servKey = sys.argv[2]
config = import_module(f"helao.config.{confPrefix}").config
C = config["servers"]
S = C[servKey]
servHost = S["host"]
servPort = S["port"]
servPy = S["bokeh"]

makeApp = import_module(f"helao.library.server.{S['group']}.{S['bokeh']}").makeBokehApp

if __name__ == "__main__":
    bokehapp = Server(
                      {f"/{servPy}": partial(makeApp, confPrefix=confPrefix, servKey=servKey)}, 
                      port=servPort, 
                      address=servHost, 
                      allow_websocket_origin=[f"{servHost}:{servPort}"]
                      )
    bokehapp.start()
    bokehapp.io_loop.add_callback(bokehapp.show, f"/{servPy}")
    bokehapp.io_loop.start()
