__all__ = ["makeBokehApp"]

import os
from importlib import import_module
from socket import gethostname

from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer

from helao.core.servers.vis import HelaoVis
from helao.core.servers.vis import Vis
from helao.helpers import helao_logging as logging
from helao.helpers.config_loader import CONFIG

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER


def find_server_names(vis: Vis, fast_key: str) -> list:
    """finds server name for a given fast driver"""
    server_names = []
    for server_name, server_config in vis.world_cfg["servers"].items():
        if server_config.get("fast", server_config.get("demo", "")) == fast_key:
            LOGGER.info(f"found server: '{fast_key}' under '{server_name}'")
            server_names.append((server_name, sorted(server_config.get("params", []))))
    return server_names


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):

    app = HelaoVis(
        server_key=server_key,
        doc=doc,
    )
    config = app.helao_cfg
    config_filename = os.path.basename(config["loaded_config_path"])

    app.vis.doc.add_root(
        layout(
            [
                Spacer(width=20),
                Div(
                    text=f"<b>Action visualizer on {gethostname().lower()} -- config: {config_filename}</b>",
                    width=1004,
                    height=32,
                    styles={"font-size": "200%", "color": "#CB4335"},
                ),
            ],
            # background="#D6DBDF",
            width=1024,
        )
    )
    app.vis.doc.add_root(Spacer(height=10))

    vis_root = f"helao.deploy.{CONFIG['deployment']}.servers.visualizer"
    vis_classes = {}
    # create visualizer objects for defined instruments
    vis_map = {
        "cpsim_server": ("oersim_vis", "C_oersimvis"),
    }
    vis_dict = {}

    for fkey, (vismod, viscls) in vis_map.items():
        vis_dict[fkey] = []
        fservnames = find_server_names(vis=app.vis, fast_key=fkey)
        for fsname, conf_pars in fservnames:
            vis_classes[viscls] = getattr(import_module(f"{vis_root}.{vismod}"), viscls)
            vis_dict[fkey].append(
                vis_classes[viscls](vis_serv=app.vis, serv_key=fsname)
            )

    return doc
