
__all__ = []


import sys
from importlib import import_module
from uvicorn.config import LOGGING_CONFIG

import uvicorn


from helaocore.helper import print_message


confPrefix = sys.argv[1]
servKey = sys.argv[2]
config = import_module(f"helao.config.{confPrefix}").config
C = config["servers"]
S = C[servKey]

makeApp = import_module(f"helao.library.server.{S['group']}.{S['fast']}").makeApp
app = makeApp(confPrefix, servKey)

if __name__ == "__main__":
    # LOGGING_CONFIG["formatters"]["default"]["fmt"] = "%(asctime)s [%(name)s] %(levelprefix)s %(message)s"
    
    LOGGING_CONFIG["formatters"]["default"]["datefmt"] = "%H:%M:%S"
    LOGGING_CONFIG["formatters"]["default"]["fmt"] = f"[%(asctime)s_{servKey}]: %(levelprefix)s %(message)s"
    LOGGING_CONFIG["formatters"]["default"]["use_colors"] = False


    LOGGING_CONFIG["formatters"]["access"]["datefmt"] = "%H:%M:%S"
    LOGGING_CONFIG["formatters"]["access"]["fmt"] = f"[%(asctime)s_{servKey}]: %(levelprefix)s %(message)s"
    LOGGING_CONFIG["formatters"]["access"]["use_colors"] = False

    print_message({}, "fast_launcher", f" ---- starting  {servKey} ----")
    uvicorn.run(app, host=S['host'], port=S['port'])
    
