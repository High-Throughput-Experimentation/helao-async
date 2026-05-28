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

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def find_server_names(vis: Vis, fast_key: str) -> list:
    """Look up server entries whose ``fast`` (or ``demo``) module matches ``fast_key``.

    Args:
        vis: Visualizer host whose ``world_cfg["servers"]`` block is searched.
        fast_key: Module short name to match against each server's ``fast`` /
            ``demo`` value (for example ``"gamry_server"``).

    Returns:
        list: ``(server_name, sorted_param_keys)`` tuples for every matching
        server entry in the configuration.
    """
    server_names = []
    for server_name, server_config in vis.world_cfg["servers"].items():
        if server_config.get("fast", server_config.get("demo", "")) == fast_key:
            LOGGER.info(f"found server: '{fast_key}' under '{server_name}'")
            server_names.append((server_name, sorted(server_config.get("params", []))))
    return server_names


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build the action-visualizer Bokeh document.

    Instantiates a :class:`HelaoVis` host, adds a header banner, then walks
    ``vis_map`` and constructs one per-action visualizer object (e.g.
    ``C_potvis``, ``C_specvis``, ``C_nidaqmxvis``) for every action server in
    the config whose ``fast``/``demo`` key matches and which is not excluded
    via the ``limit_vis`` server parameter. Each visualizer attaches its own
    layout and WebSocket subscriber to ``doc``.

    Args:
        doc: Bokeh document supplied by the Bokeh server for this session.
        confPrefix: Config prefix passed by ``bokeh_launcher.py``.
        server_key: Visualizer server key from the configuration.
        helao_repo_root: Absolute path to the HELAO repo root.

    Returns:
        Bokeh ``Document``: The same ``doc`` passed in, with all visualizer
        layouts mounted as roots.
    """

    app = HelaoVis(
        server_key=server_key,
        doc=doc,
    )
    config = app.helao_cfg
    config_filename = os.path.basename(config["loaded_config_path"])

    limit_vis = app.server_params.get("limit_vis", [])

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
        "biologic_server": ("biologic_vis", "C_biovis"),
        "potentiostat_server": ("gamry_vis", "C_potvis"),
        "gamry_server": ("gamry_vis", "C_potvis"),
        "gamry_server2": ("gamry_vis", "C_potvis"),
        "spec_server": ("spec_vis", "C_specvis"),
        "nidaqmx_server": ("nidaqmx_vis", "C_nidaqmxvis"),
        "pal_server": ("pal_vis", "C_palvis"),
        "cpsim_server": ("oersim_vis", "C_oersimvis"),
        "power_supply_server": ("power_supply_vis", "C_powersupplyvis"),
    }
    vis_dict = {}

    for fkey, (vismod, viscls) in vis_map.items():
        vis_dict[fkey] = []
        fservnames = find_server_names(vis=app.vis, fast_key=fkey)
        for fsname, conf_pars in fservnames:
            if limit_vis and fsname not in limit_vis:
                continue
            vis_classes[viscls] = getattr(import_module(f"{vis_root}.{vismod}"), viscls)
            vis_dict[fkey].append(
                vis_classes[viscls](vis_serv=app.vis, serv_key=fsname)
            )

    return doc
