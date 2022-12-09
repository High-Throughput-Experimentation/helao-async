__all__ = ["makeBokehApp"]

import asyncio
from socket import gethostname

from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer

from helaocore.models.hlostatus import HloStatus
from helao.helpers.make_vis_serv import makeVisServ
from helao.servers.vis import Vis
from helao.helpers.config_loader import config_loader
from helao.servers.visualizer.co2_vis import C_co2
from helao.servers.visualizer.pressure_vis import C_pressure
from helao.servers.visualizer.temp_vis import C_temperature


valid_data_status = (
    None,
    HloStatus.active,
)


def async_partial(f, *args):
    async def f2(*args2):
        result = f(*args, *args2)
        if asyncio.iscoroutinefunction(f):
            result = await result
        return result

    return f2


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


def makeBokehApp(doc, confPrefix, servKey, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = makeVisServ(
        config=config,
        server_key=servKey,
        doc=doc,
        server_title=servKey,
        description="Sensor Visualizer",
        version=2.0,
        driver_class=None,
    )

    app.vis.doc.add_root(
        layout(
            [
                Spacer(width=20),
                Div(
                    text=f"<b>Sensors on {gethostname()}</b>",
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
    vis_map = {"sensor_server": C_co2,
        "sensor_server": C_pressure,
        "sensor_server": C_temperature,
        }
    vis_dict = {}

    for fkey, viscls in vis_map.items():
        vis_dict[fkey] = []
        fservnames = find_server_names(vis=app.vis, fast_key=fkey)
        for fsname in fservnames:
            vis_dict[fkey].append(viscls(visServ=app.vis, serv_key=fsname))

    return doc
