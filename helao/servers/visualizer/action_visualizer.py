__all__ = ["makeBokehApp"]

from socket import gethostname

from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer

from helao.servers.vis import HelaoVis
from helao.servers.vis import Vis
from helao.helpers.config_loader import config_loader
from helao.servers.visualizer.gamry_vis import C_potvis
from helao.servers.visualizer.nidaqmx_vis import C_nidaqmxvis
from helao.servers.visualizer.pal_vis import C_palvis
from helao.servers.visualizer.spec_vis import C_specvis


def find_server_names(vis: Vis, fast_key: str) -> list:
    """finds server name for a given fast driver"""
    server_names = []
    for server_name, server_config in vis.world_cfg["servers"].items():
        if server_config.get("fast", "") == fast_key:
            vis.print_message(
                f"found server: '{fast_key}' under '{server_name}'", info=True
            )
            server_names.append(server_name)

    return server_names


def makeBokehApp(doc, confPrefix, server_key, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = HelaoVis(
        config=config,
        server_key=server_key,
        doc=doc,
    )

    app.vis.doc.add_root(
        layout(
            [
                Spacer(width=20),
                Div(
                    text=f"<b>Visualizer on {gethostname()}</b>",
                    width=1004,
                    height=32,
                    style={"font-size": "200%", "color": "red"},
                ),
            ],
            background="#C0C0C0",
            width=1024,
        )
    )
    app.vis.doc.add_root(Spacer(height=10))

    # create visualizer objects for defined instruments
    vis_map = {
        "gamry_server": C_potvis,
        "nidaqmx_server": C_nidaqmxvis,
        "pal_server": C_palvis,
        "spec_server": C_specvis,
        }
    vis_dict = {}

    for fkey, viscls in vis_map.items():
        vis_dict[fkey] = []
        fservnames = find_server_names(vis=app.vis, fast_key=fkey)
        for fsname in fservnames:
            vis_dict[fkey].append(viscls(visServ=app.vis, serv_key=fsname))

    return doc
