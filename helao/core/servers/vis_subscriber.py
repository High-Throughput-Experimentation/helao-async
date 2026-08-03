"""Shared base classes for HELAO Bokeh data-subscriber visualizers.

Every ``*_vis.py`` module under ``helao/deploy/*/servers/visualizer/`` defines
a single ``C_*`` class that mounts a Bokeh layout on a :class:`Vis` document and
streams data from an action server's WebSocket. Aside from the data-specific
plotting code, these classes share an identical bring-up sequence: resolve the
target server from the world config, open a :class:`WsSubscriber`, wire up the
``max datapoints`` / ``update sec`` inputs, and run an asyncio ingest loop that
schedules plot updates on the Bokeh document thread.

This module factors that shared logic into :class:`VisSubscriber` and the two
category specializations callers inherit from:

* :class:`LiveVisualizer` subscribes to the ``ws_live`` endpoint (continuous
  sensor telemetry).
* :class:`ActionVisualizer` subscribes to the ``ws_data`` endpoint (per-action
  measurement packages).

A subclass typically calls ``super().__init__(...)``, returns early when
``self.connected`` is ``False``, builds its data sources / widgets / layout, and
then calls :meth:`VisSubscriber._mount` to register the document roots and start
the ingest task. Subclasses provide the data-specific :meth:`add_points` (and
usually ``_add_plots`` / ``reset_plot``) methods.
"""

__all__ = [
    "VisSubscriber",
    "LiveVisualizer",
    "ActionVisualizer",
    "VIS_CLASS_NAME",
    "import_vis_class",
    "mount_visualizers",
]

import asyncio
import time
from functools import lru_cache, partial
from importlib import import_module
from importlib import util as importlib_util

from bokeh.layouts import Spacer

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

from helao.core.servers.vis import Vis
from helao.helpers import config_loader
from helao.core.servers.reflex.discovery import (
    deployment_search_order as _deployment_search_order,
)
from helao.helpers.loaded_modules import write_loaded_modules_snapshot
from helao.helpers.ws_utils import WsSubscriber as Wss

#: Common class name every ``*_vis.py`` module exposes. The generic
#: ``action_visualizer``/``live_visualizer`` Bokeh apps look up this attribute
#: after importing a vis module named in an action server's ``action_vis`` /
#: ``live_vis`` config key, so all per-instrument visualizer classes share it.
VIS_CLASS_NAME = "C_vis"


@lru_cache(maxsize=None)
def import_vis_class(module_name: str, class_name: str = VIS_CLASS_NAME):
    """Import a visualizer class by module short name, searching deployments.

    Looks for ``helao.deploy.<deployment>.servers.visualizer.<module_name>`` in
    :func:`_deployment_search_order` order and returns the first module's
    ``class_name`` attribute. ``find_spec`` is used to probe each deployment so
    that a module which exists but fails to import surfaces its real error
    instead of being silently skipped.

    The resolved class is cached per ``(module_name, class_name)``: the
    deployment search order is fixed for a running process, so this avoids
    repeating the ``find_spec`` probe and ``os.listdir`` deployment scan on
    every Bokeh session. Only the class *resolution* is cached; ``mount_visualizers``
    still instantiates a fresh visualizer (with its own data sources and
    WebSocket) per client.

    Args:
        module_name: Short module name from a server's ``action_vis`` /
            ``live_vis`` config key (e.g. ``"gamry_vis"``).
        class_name: Attribute to fetch from the module (defaults to
            :data:`VIS_CLASS_NAME`).

    Returns:
        type: The resolved visualizer class.

    Raises:
        ModuleNotFoundError: If no deployment provides ``module_name``.
    """
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
    """Instantiate visualizer modules declared by action servers in the config.

    Walks every server entry in the world config and, for those carrying
    ``vis_cfg_key`` (``"action_vis"`` or ``"live_vis"``), imports the named
    module(s) via :func:`import_vis_class` and instantiates the visualizer
    against that server. Servers excluded by the host visualizer's optional
    ``limit_vis`` server parameter are skipped. The value may be a single
    module name or a list of module names.

    Args:
        app: The :class:`HelaoVis` host exposing ``server_params`` and ``vis``.
        vis_cfg_key: Config key naming the vis module(s) to mount.

    Returns:
        list: The instantiated visualizer objects (mounted on the document).
    """
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
            viscls = import_vis_class(module_name)
            LOGGER.info(
                f"mounting '{module_name}.{VIS_CLASS_NAME}' for server '{server_name}'"
            )
            instances.append(viscls(vis_serv=app.vis, serv_key=server_name))

    # Refresh the hot-reload loaded-modules snapshot now that the per-server
    # ``*_vis`` modules have been lazily imported. bokeh_launcher writes a
    # startup snapshot before any Bokeh session connects, so it cannot see the
    # vis modules resolved here (import_vis_class runs per session); without this
    # refresh, editing a ``*_vis`` module never maps to this bokeh server and the
    # watcher never restarts it. Best-effort; helper swallows its own errors.
    if instances:
        helaodirs = getattr(app.vis, "helaodirs", None)
        states_root = getattr(helaodirs, "states_root", None) if helaodirs else None
        if states_root is not None:
            snap = write_loaded_modules_snapshot(
                states_root, app.vis.server.server_name
            )
            if snap is not None:
                LOGGER.info(f"refreshed loaded-modules snapshot: {snap}")
    return instances


class VisSubscriber:
    """Common bring-up for Bokeh visualizers backed by an action-server WebSocket.

    The constructor resolves the target server from the world config and, when
    found, opens a :class:`WsSubscriber` on :attr:`WS_PATH`. Subclasses build
    their own Bokeh widgets, plots, and ``self.layout`` then call
    :meth:`_mount` to attach the layout and launch :meth:`IOloop_data`.

    Class attributes:
        WS_PATH: WebSocket path subscribed to (``"ws_live"`` or ``"ws_data"``).
        USE_WSS: Whether to open a :class:`WsSubscriber` during ``__init__``.
            Set ``False`` by subclasses that manage their own connection.
        GUARD_EMPTY_MESSAGES: When ``True``, :meth:`IOloop_data` only schedules
            :meth:`add_points` when the subscriber returned messages.
        DEFAULT_MAX_POINTS: Fallback rolling-window length for the data source.
        DEFAULT_UPDATE_RATE: Fallback minimum seconds between WebSocket polls.
        SUBSCRIBE_LABEL: Human-readable label used in the ingest log line.

    Attributes:
        vis: Host :class:`Vis` instance providing the Bokeh document.
        config_dict: ``params`` block from the visualizer's server config.
        max_points: Rolling-window length for the data source.
        update_rate: Minimum seconds between WebSocket polls.
        last_update_time: Epoch timestamp of the most recent poll.
        serv_key: Configuration key of the subscribed action server.
        serv_config: World-config mapping for the action server, or ``None``.
        connected: ``True`` when ``serv_key`` resolved to a config entry.
        host: Action server hostname (only set when connected).
        port: Action server port (only set when connected).
        data_url: Fully formed ``ws://`` URL for the subscribed WebSocket.
        wss: :class:`WsSubscriber` for :attr:`WS_PATH`, or ``None``.
        IOloop_data_run: Liveness flag for the data ingestion task.
        IOloop_stat_run: Liveness flag for the status ingestion task.
        IOtask: ``asyncio`` task running :meth:`IOloop_data` (set by
            :meth:`_mount`).
    """

    WS_PATH = "ws_data"
    USE_WSS = True
    GUARD_EMPTY_MESSAGES = False
    DEFAULT_MAX_POINTS = 500
    DEFAULT_UPDATE_RATE = 0.5
    SUBSCRIBE_LABEL = "visualizer"

    def __init__(
        self,
        vis_serv: Vis,
        serv_key: str,
        *,
        max_points: int = None,
        update_rate: float = None,
    ):
        """Resolve the target server and open its WebSocket subscriber.

        Args:
            vis_serv: Host :class:`Vis` server providing the Bokeh document.
            serv_key: Configuration key of the action server to subscribe to.
                When it is absent from the world config, ``__init__`` returns
                early with ``self.connected`` set to ``False`` and subclasses
                should likewise return without registering any roots.
            max_points: Optional override for :attr:`DEFAULT_MAX_POINTS`.
            update_rate: Optional override for the configured update rate.
        """
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
        self.wss = Wss(self.host, self.port, self.WS_PATH) if self.USE_WSS else None

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

    def _mount(self, add_spacer: bool = True):
        """Attach ``self.layout`` to the document and start the ingest task.

        Args:
            add_spacer: When ``True``, also add a trailing ``Spacer`` root to
                separate stacked visualizer modules.
        """
        self.vis.doc.add_root(self.layout)
        if add_spacer:
            self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)

    def cleanup_session(self, session_context):
        """Cancel the data ingest task when the Bokeh session is torn down.

        Args:
            session_context: Bokeh session context (unused).
        """
        LOGGER.info(f"'{self.serv_key}' Bokeh session closed")
        self.IOloop_data_run = False
        self.IOtask.cancel()

    def update_input_value(self, sender, value):
        """Write ``value`` back onto a Bokeh input widget on the document thread.

        Args:
            sender: Bokeh input widget whose ``value`` is being updated.
            value: New string value to assign.
        """
        sender.value = value

    def callback_input_max_points(self, attr, old, new, sender):
        """Validate the ``max datapoints`` input and update the rolling window.

        Parses ``new`` as an int, falls back to ``old`` (or ``500``) on bad
        input, then clamps to ``[2, 10000]`` before storing it as
        ``self.max_points`` and refreshing the widget.

        Args:
            attr: Bokeh property name that changed.
            old: Prior text value.
            new: New text value typed by the user.
            sender: The :class:`TextInput` to refresh.
        """

        def to_int(val):
            try:
                return int(val)
            except ValueError:
                return None

        newpts = to_int(new)
        oldpts = to_int(old)

        if newpts is None:
            if oldpts is not None:
                newpts = oldpts
            else:
                newpts = 500

        if newpts < 2:
            newpts = 2
        if newpts > 10000:
            newpts = 10000

        self.max_points = newpts

        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.max_points}")
        )

    def callback_input_update_rate(self, attr, old, new, sender):
        """Validate the ``update sec`` input and adjust the polling cadence.

        Parses ``new`` as a float (defaulting to ``0.5`` on bad input), stores
        it as ``self.update_rate``, and writes the value back to the widget.

        Args:
            attr: Bokeh property name that changed.
            old: Prior text value.
            new: New text value typed by the user.
            sender: The :class:`TextInput` to refresh.
        """

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
        """Continuously read the WebSocket and schedule plot updates.

        Sleeps briefly each iteration, respects ``self.update_rate`` as a
        minimum gap between polls, and dispatches message batches to
        :meth:`add_points` on the document thread. When
        :attr:`GUARD_EMPTY_MESSAGES` is ``True`` empty batches are skipped.
        """
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
        """Ingest a batch of WebSocket messages into the data source.

        Args:
            datapackage_list: Messages drained from the subscriber.

        Raises:
            NotImplementedError: Subclasses must provide the data-specific
                ingestion logic.
        """
        raise NotImplementedError


class LiveVisualizer(VisSubscriber):
    """Base class for ``ws_live`` visualizers (continuous sensor telemetry).

    Subscribes to the action server's ``ws_live`` WebSocket and only schedules
    plot updates when new samples arrive.
    """

    WS_PATH = "ws_live"
    GUARD_EMPTY_MESSAGES = True
    DEFAULT_UPDATE_RATE = 0.5
    SUBSCRIBE_LABEL = "live visualizer"


class ActionVisualizer(VisSubscriber):
    """Base class for ``ws_data`` visualizers (per-action measurement packages).

    Subscribes to the action server's ``ws_data`` WebSocket and polls at a fast
    default cadence, forwarding every batch (including empty ones) so that
    action/UUID transitions are detected promptly.
    """

    WS_PATH = "ws_data"
    GUARD_EMPTY_MESSAGES = False
    DEFAULT_UPDATE_RATE = 1e-3
    SUBSCRIBE_LABEL = "action visualizer"
