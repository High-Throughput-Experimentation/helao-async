from socket import gethostname

from helao.core.helper import print_message
from helao.core.server import HelaoBokehAPI


class Vis(object):
    """Base class for all HELAO bokeh servers."""

    def __init__(self, bokehapp: HelaoBokehAPI):
        self.server_name = bokehapp.helao_srv
        self.server_cfg = bokehapp.world_cfg["servers"][self.server_name]
        self.world_cfg = bokehapp.world_cfg
        self.hostname = gethostname()
        self.doc = bokehapp.doc
        # self.save_root = None
        # self.technique_name = None
        # self.aloop = asyncio.get_running_loop()

    def print_message(self, *args, **kwargs):
        print_message(self.server_cfg, self.server_name, *args, **kwargs)
