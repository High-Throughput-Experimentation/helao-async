__all__ = ["Vis", "HelaoVis"]

from socket import gethostname

from helao.helpers.server_api import HelaoBokehAPI
from helao.helpers.helao_dirs import helao_dirs
from helao.helpers.print_message import print_message
from helaocore.models.machine import MachineModel


# TODO: HelaoVis will return doc to replace makeBokehApp func
class HelaoVis(HelaoBokehAPI):
    def __init__(
        self,
        config,
        server_key,
        doc,
    ):
        super().__init__(config, server_key, doc)
        self.vis = Vis(self)


class Vis:
    """Base class for all HELAO bokeh servers."""

    def __init__(self, bokehapp: HelaoBokehAPI):
        self.server = MachineModel(
            server_name=bokehapp.helao_srv, machine_name=gethostname().lower()
        )
        self.server_cfg = bokehapp.helao_cfg["servers"][self.server.server_name]
        self.world_cfg = bokehapp.helao_cfg
        self.doc = bokehapp.doc

        self.helaodirs = helao_dirs(self.world_cfg, self.server.server_name)

        if self.helaodirs.root is None:
            raise ValueError(
                "Warning: root directory was not defined. Logs, PRCs, PRGs, and data will not be written.",
                error=True,
            )

    def print_message(self, *args, **kwargs):
        print_message(
            self.server_cfg,
            self.server.server_name,
            log_dir=self.helaodirs.log_root,
            *args,
            **kwargs
        )
