__all__ = ["makeBokehApp"]

from socket import gethostname

from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer

from helao.servers.vis import HelaoVis
from helao.servers.vis import Vis
from helao.helpers.config_loader import config_loader
from helao.servers.visualizer.co2_vis import C_co2
from helao.servers.visualizer.pressure_vis import C_pressure
from helao.servers.visualizer.temp_vis import C_temperature
from helao.servers.visualizer.mfc_vis import C_mfc
from helao.servers.visualizer.wssim_live_vis import C_simlivevis


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
                    text=f"<b>Sensors on {gethostname().lower()}</b>",
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
        "co2sensor_server": C_co2,
        "galil_io": C_pressure,
        "nidaqmx_server": C_temperature,
        "mfc_server": C_mfc,
        "ws_simulator": C_simlivevis,
    }
    vis_dict = {}

    for fkey, viscls in vis_map.items():
        vis_dict[fkey] = []
        fservnames = find_server_names(vis=app.vis, fast_key=fkey)
        for fsname in fservnames:
            vis_dict[fkey].append(viscls(vis_serv=app.vis, serv_key=fsname))

    return doc
