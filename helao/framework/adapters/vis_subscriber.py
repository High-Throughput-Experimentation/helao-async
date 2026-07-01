"""Bokeh ws-subscriber base classes + deployment C_vis discovery (adapter).

Ports legacy ``core/servers/vis_subscriber.py`` into the framework ``adapters/``
layer. This is an I/O adapter: it owns a WebSocket client and streams batches
into Bokeh ``ColumnDataSource``s on the document thread. Plot-specific code
lives in deployment ``C_vis`` subclasses.
"""

__all__ = [
    "VisSubscriber",
    "LiveVisualizer",
    "ActionVisualizer",
    "VIS_CLASS_NAME",
    "import_vis_class",
    "mount_visualizers",
]

import os
import json
import time
import asyncio
from functools import partial
from importlib import import_module, util as importlib_util

from bokeh.layouts import Spacer

from helao.framework.support import helao_logging as logging
from helao.framework.support import config_loader
from helao.helpers.ws_utils import WsSubscriber as Wss
from helao.framework.models.data import DataPackageModel


def _decode_data_package(raw):
    """Decode a framework ``send_json`` data frame into a ``DataPackageModel``.

    Framework action servers relay ws_data/ws_live as JSON
    (``BaseAPI._ws_relay`` sends ``DataPackageModel.as_dict()``). Reconstructing
    the model restores the object/typed access the (legacy-ported) vis code
    expects; ``json.loads`` alone would hand the vis a plain dict with a string
    ``status`` that never matches the ``HloStatus`` members in
    ``VALID_DATA_STATUS``.
    """
    return DataPackageModel.model_validate(json.loads(raw))

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

VIS_CLASS_NAME = "C_vis"


def _deploy_root() -> str:
    """Return ``<repo>/helao/deploy`` resolved from this file's location."""
    here = os.path.abspath(__file__)
    # <repo>/helao/framework/adapters/vis_subscriber.py
    helao_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(helao_root, "deploy")


def _deployment_search_order() -> list:
    """Deployment names to search when resolving a vis module."""
    order = []
    cfg = config_loader.CONFIG or {}
    current = cfg.get("deployment")
    if current:
        order.append(current)
    if "hte" not in order:
        order.append("hte")
    deploy_root = _deploy_root()
    if os.path.isdir(deploy_root):
        for name in sorted(os.listdir(deploy_root)):
            if name in order:
                continue
            if os.path.isdir(os.path.join(deploy_root, name, "servers", "visualizer")):
                order.append(name)
    return order


def import_vis_class(module_name: str, class_name: str = VIS_CLASS_NAME):
    """Import a visualizer class by module short name, searching deployments."""
    tried = []
    for deployment in _deployment_search_order():
        modpath = f"helao.deploy.{deployment}.servers.visualizer.{module_name}"
        tried.append(modpath)
        try:
            spec = importlib_util.find_spec(modpath)
        except ModuleNotFoundError:
            spec = None
        if spec is None:
            continue
        module = import_module(modpath)
        return getattr(module, class_name)
    raise ModuleNotFoundError(
        f"could not locate visualizer module '{module_name}' in any deployment; "
        f"tried: {tried}"
    )


def mount_visualizers(app, vis_cfg_key: str) -> list:
    """Instantiate visualizer modules declared by action servers in the config."""
    limit_vis = app.server_params.get("limit_vis", [])
    instances = []
    for server_name, server_config in app.vis.world_cfg["servers"].items():
        if not isinstance(server_config, dict):
            continue
        module_names = server_config.get(vis_cfg_key)
        if not module_names:
            continue
        if limit_vis and server_name not in limit_vis:
            continue
        if isinstance(module_names, str):
            module_names = [module_names]
        for module_name in module_names:
            # Isolate each visualizer: one module that fails to import or raises
            # in its constructor must NOT abort the whole mount and drop every
            # later server's visualizer (e.g. a broken pal_vis was swallowing
            # spec_vis). Log the failure with a traceback and carry on.
            try:
                viscls = import_vis_class(module_name)
                LOGGER.info(
                    f"mounting '{module_name}.{VIS_CLASS_NAME}' for server '{server_name}'"
                )
                instances.append(viscls(vis_serv=app.vis, serv_key=server_name))
            except Exception:
                LOGGER.error(
                    f"failed to mount '{module_name}' for server '{server_name}'; "
                    "skipping it so the remaining visualizers still load",
                    exc_info=True,
                )
    return instances


class VisSubscriber:
    """Common bring-up for Bokeh visualizers backed by an action-server WebSocket."""

    WS_PATH = "ws_data"
    USE_WSS = True
    GUARD_EMPTY_MESSAGES = False
    DEFAULT_MAX_POINTS = 500
    DEFAULT_UPDATE_RATE = 0.5
    SUBSCRIBE_LABEL = "visualizer"

    def __init__(self, vis_serv, serv_key, *, max_points: int = None, update_rate: float = None):
        self.vis = vis_serv
        self.config_dict = self.vis.server_cfg.get("params", {})
        self.max_points = self.DEFAULT_MAX_POINTS if max_points is None else max_points
        self.update_rate = (
            self.config_dict.get("update_rate", self.DEFAULT_UPDATE_RATE)
            if update_rate is None
            else update_rate
        )
        self.last_update_time = time.time()

        self.serv_key = serv_key
        self.serv_config = self.vis.world_cfg["servers"].get(serv_key, None)
        self.connected = self.serv_config is not None
        if not self.connected:
            return

        self.host = self.serv_config.get("host", None)
        self.port = self.serv_config.get("port", None)
        self.data_url = f"ws://{self.host}:{self.port}/{self.WS_PATH}"
        # framework action servers relay ws_data/ws_live as JSON (BaseAPI.
        # _ws_relay send_json == DataPackageModel.as_dict()), not the legacy
        # zstd+pickle object. Reconstruct the model so the vis keeps its object
        # access (data_package.datamodel.status / .action_name) and typed fields
        # (HloStatus) — a plain dict would leave status as a str and never match
        # VALID_DATA_STATUS (HloStatus enums), silently dropping all data.
        self.wss = (
            Wss(self.host, self.port, self.WS_PATH, decode=_decode_data_package)
            if self.USE_WSS
            else None
        )

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

    def _mount(self, add_spacer: bool = True):
        self.vis.doc.add_root(self.layout)
        if add_spacer:
            self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)

    def cleanup_session(self, session_context):
        LOGGER.info(f"'{self.serv_key}' Bokeh session closed")
        self.IOloop_data_run = False
        self.IOtask.cancel()

    def update_input_value(self, sender, value):
        sender.value = value

    def callback_input_max_points(self, attr, old, new, sender):
        def to_int(val):
            try:
                return int(val)
            except ValueError:
                return None

        newpts = to_int(new)
        oldpts = to_int(old)
        if newpts is None:
            newpts = oldpts if oldpts is not None else 500
        if newpts < 2:
            newpts = 2
        if newpts > 10000:
            newpts = 10000
        self.max_points = newpts
        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.max_points}")
        )

    def callback_input_update_rate(self, attr, old, new, sender):
        def to_float(val):
            try:
                return float(val)
            except ValueError:
                return 0.5

        self.update_rate = to_float(new)
        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.update_rate}")
        )

    async def IOloop_data(self):
        LOGGER.info(f" ... {self.SUBSCRIBE_LABEL} subscribing to: {self.data_url}")
        while True:
            if time.time() - self.last_update_time >= self.update_rate:
                messages = await self.wss.read_messages()
                if messages or not self.GUARD_EMPTY_MESSAGES:
                    self.vis.doc.add_next_tick_callback(
                        partial(self.add_points, messages)
                    )
                    self.last_update_time = time.time()
            await asyncio.sleep(0.01)

    def add_points(self, datapackage_list: list):
        raise NotImplementedError


class LiveVisualizer(VisSubscriber):
    """``ws_live`` visualizers (continuous sensor telemetry)."""

    WS_PATH = "ws_live"
    GUARD_EMPTY_MESSAGES = True
    DEFAULT_UPDATE_RATE = 0.5
    SUBSCRIBE_LABEL = "live visualizer"


class ActionVisualizer(VisSubscriber):
    """``ws_data`` visualizers (per-action measurement packages)."""

    WS_PATH = "ws_data"
    GUARD_EMPTY_MESSAGES = False
    DEFAULT_UPDATE_RATE = 1e-3
    SUBSCRIBE_LABEL = "action visualizer"
