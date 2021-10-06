# __init__.py
import sys

import colorama

from .api import HelaoBokehAPI, HelaoFastAPI
from .async_private_dispatcher import async_private_dispatcher
from .async_process_dispatcher import async_process_dispatcher
from .base import Base
from .import_sequences import import_sequences
from .make_orch_serv import makeOrchServ
from .make_vis_serv import makeVisServ
from .orch import Orch
from .process_start_condition import process_start_condition
from .setup_process import setup_process
from .vis import Vis

# ANSI color codes converted to the Windows versions
colorama.init(strip=not sys.stdout.isatty())  # strip colors if stdout is redirected
# colorama.init()

# version number, gets written into every prc/prg and hlo file
hlo_version = "2021.09.20"
