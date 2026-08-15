import asyncio
import json
from datetime import datetime
from functools import partial

import websockets
from bokeh.layouts import Spacer, layout
from bokeh.models import (
    CheckboxButtonGroup,
    ColumnDataSource,
    DataTable,
    TableColumn,
    TextInput,
)
from bokeh.models.widgets import Div

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.core.error import ErrorCodes
from helao.core.models.data import DataPackageModel
from helao.core.models.hlostatus import HloStatus
from helao.ui.shared.palette import PANEL_BG, panel_styles
from helao.ui.bokeh.theme import SECTION_MARGIN, stretch_section
from helao.ui.bokeh.vis import Vis
from helao.ui.bokeh.vis_subscriber import ActionVisualizer
from helao.helpers.dispatcher import async_private_dispatcher

valid_data_status = (
    None,
    HloStatus.active,
)


def async_partial(f, *args):
    """Build an async wrapper that pre-binds ``args`` to ``f``.

    The returned coroutine function accepts further positional arguments and
    invokes ``f`` with the combined argument list, awaiting it when ``f`` is
    itself a coroutine function.

    Args:
        f: Callable (sync or async) to be partially applied.
        *args: Positional arguments bound ahead of any later call arguments.

    Returns:
        Coroutine function: ``async def`` wrapper around ``f``.
    """

    async def f2(*args2):
        """Inner coroutine that forwards ``args + args2`` to ``f``."""
        result = f(*args, *args2)
        if asyncio.iscoroutinefunction(f):
            result = await result
        return result

    return f2


class C_vis(ActionVisualizer):
    """Bokeh visualizer for the SAMPLE (archive) server.

    Polls the SAMPLE server's ``list_new_samples`` private endpoint whenever
    new data is observed on the ``ws_data`` WebSocket and renders one
    Bokeh ``DataTable`` per sample type (solid, liquid, gas, assembly)
    showing the newest entries. This visualizer manages its own WebSocket
    connection (``USE_WSS = False``) and overrides :meth:`IOloop_data`, but
    inherits the shared bring-up, :meth:`cleanup_session`, and
    :meth:`update_input_value` from :class:`ActionVisualizer`.

    Attributes:
        max_width: Maximum layout width in pixels.
        max_smps: Number of latest samples to request per type.
        data_dict_keys: Column names rendered per sample table.
        data_dict: Backing dict-of-dicts keyed by sample type.
        datasource: :class:`ColumnDataSource` per sample type.
        sample_tables: :class:`DataTable` per sample type.
        layout: Composed Bokeh layout mounted on the document.
        input_max_smps: Widget setting ``max_smps``.
        inheritance_selector_group: Checkbox controlling the ``give_only``
            filter on the SAMPLE request.
        inheritance_select: Cached active list of the inheritance selector.
    """

    USE_WSS = False

    def __init__(self, vis_serv: Vis, serv_key: str):
        """Wire up data sources, tables, widgets, and start the WS ingest task.

        Args:
            vis_serv: Host :class:`Vis` server providing the Bokeh document.
            serv_key: Configuration key of the SAMPLE action server. If the
                server is not in the config, ``__init__`` returns early
                without registering any roots.
        """
        super().__init__(vis_serv, serv_key)
        if not self.connected:
            return
        self.max_width = 1024
        self.max_smps = 10

        smptypes = ["solid", "liquid", "gas", "assembly"]

        self.data_dict_keys = [
            "global_label",
            "sample_creation_timecode",
            "comment",
            "volume_ml",
            "ph",
            "electrolyte",
        ]
        self.data_dict = {
            smptype: {key: [] for key in self.data_dict_keys} for smptype in smptypes
        }

        self.datasource = {
            smptype: ColumnDataSource(data=self.data_dict[smptype])
            for smptype in smptypes
        }

        self.sample_tables = {
            smptype: DataTable(
                source=self.datasource[smptype],
                columns=[TableColumn(field=k, title=k) for k in self.data_dict_keys],
                width=self.max_width - 20,
                height=200,
                # "fit_columns" triggers a Bokeh JS crash in SlickGrid's
                # autosizeColumns/getColContentSize ("row is not defined") that
                # aborts the whole document render -> every visualizer mounted
                # after sample_vis (e.g. spec_vis) silently disappears, and the
                # sample tables render collapsed. "force_fit" fits columns to
                # the table width without the content-size autosize path
                # (matches the operator's working DataTables).
                autosize_mode="force_fit",
            )
            for smptype in smptypes
        }

        # create visual elements
        self.layout = []

        # input field widget
        self.input_max_smps = TextInput(
            value=f"{self.max_smps}",
            title="num latest samples to return",
            disabled=False,
            width=150,
        )
        # execute on input field change
        self.input_max_smps.on_change(
            "value",
            partial(self.callback_input_max_smps, sender=self.input_max_smps),
        )

        # selector for give_only inheritance
        #
        # height=31 matches a TextInput's input box, so this lines up with the
        # box beside it; the previous height=40 stood 9px taller and sat 19px
        # low. Its label Div below is height=17 to mirror a TextInput's own
        # title label (12px font, 17.14px line-height, no margin) — measured,
        # because the pairing only reads as aligned if the label above each
        # control is the same height.
        self.inheritance_selector_group = CheckboxButtonGroup(
            labels=["give_only"],
            active=[],
            width=150,
            height=31,
        )
        self.inheritance_selector_group.on_change(
            "active",
            partial(self.callback_inheritance, sender=self.inheritance_selector_group),
        )
        self.inheritance_select = self.inheritance_selector_group.active

        # combine all sublayouts into a single one
        self.layout = layout(
            [
                [
                    Spacer(width=20),
                    Div(
                        text=f'<b>Sample Visualizer module for server <a href="http://{self.host}:{self.port}/docs#/" target="_blank">\'{self.serv_key}\'</a></b>',
                        sizing_mode="stretch_width",
                        height=15,
                    ),
                ],
                [
                    self.input_max_smps,
                    Spacer(width=50),
                    [
                        # height/font/margin mirror a TextInput's own title
                        # label (17px tall, 12px font, no margin — measured), so
                        # this stand-in label leaves the group at exactly the
                        # height of the input box in the same row. margin=0 is
                        # the load-bearing part: a Div's default 5px margin was
                        # pushing the group 10px low all by itself.
                        Div(
                            text="filter by inheritance:",
                            width=150,
                            height=17,
                            margin=0,
                            styles={"font-size": "12px"},
                        ),
                        self.inheritance_selector_group,
                    ],
                ],
                [
                    Spacer(width=20),
                    Div(
                        text="<b>Newest liquid samples:</b>", width=200 + 50, height=15
                    ),
                ],
                [self.sample_tables["liquid"]],
                [
                    Spacer(width=20),
                    Div(
                        text="<b>Newest assembly samples:</b>",
                        width=200 + 50,
                        height=15,
                    ),
                ],
                [self.sample_tables["assembly"]],
                [
                    Spacer(width=20),
                    Div(text="<b>Newest gas samples:</b>", width=200 + 50, height=15),
                ],
                [self.sample_tables["gas"]],
                [
                    Spacer(width=20),
                    Div(text="<b>Newest solid samples:</b>", width=200 + 50, height=15),
                ],
                [self.sample_tables["solid"]],
                Spacer(height=10),
            ],
            styles=panel_styles(PANEL_BG),
            margin=SECTION_MARGIN,
        )
        stretch_section(self.layout)

        self.reset_plot()

        self._mount()

    def callback_input_max_smps(self, attr, old, new, sender):
        """Validate the ``num latest samples`` input and refresh the tables.

        Parses ``new`` as an int, stores it as ``self.max_smps``, refreshes
        the widget value, and triggers :meth:`reset_plot` to re-query the
        SAMPLE server.

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
        self.max_smps = newpts
        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.max_smps}")
        )
        self.reset_plot()

    def update_inheritance_selector(self):
        """Cache the current state of the ``give_only`` checkbox selector."""
        self.inheritance_select = self.inheritance_selector_group.active

    def callback_inheritance(self, attr, old, new, sender):
        """Sync the cached inheritance filter and reload sample tables.

        Args:
            attr: Bokeh property name that changed.
            old: Previous selection list.
            new: Updated selection list.
            sender: The checkbox group that emitted the change.
        """
        self.vis.doc.add_next_tick_callback(partial(self.update_inheritance_selector))
        self.reset_plot()

    async def add_points(self):
        """Query the SAMPLE server for the newest samples and refresh every table.

        Issues a ``list_new_samples`` private dispatch with the current
        ``max_smps`` and inheritance filter, formats the creation timestamps
        as human-readable strings, and assigns the resulting per-type lists
        to each ``ColumnDataSource``.
        """
        # pull latest sample lists from SAMPLE server and populate self.datasource.data
        # keep global_label, sample_creation_timecode, comment, volume, ph, electrolyte
        resp, err = await async_private_dispatcher(
            self.serv_key,
            self.host,
            self.port,
            "list_new_samples",
            {
                "num_smps": self.max_smps,
                "give_only": "true" if 0 in self.inheritance_select else "false",
            },
            {},
        )
        if err == ErrorCodes.none:
            for smptype in ["solid", "liquid", "gas", "assembly"]:
                for k in self.data_dict_keys:
                    self.data_dict[smptype][k] = [d.get(k, None) for d in resp[smptype]]
                self.data_dict[smptype]["sample_creation_timecode"] = [
                    datetime.fromtimestamp(v / 1e9).strftime("%Y-%m-%d %H:%M:%S")
                    for v in self.data_dict[smptype]["sample_creation_timecode"]
                ]
                self.datasource[smptype].data = self.data_dict[smptype]

    async def IOloop_data(self):
        """Subscribe to the SAMPLE data WebSocket and refresh tables on activity.

        Connects directly with :mod:`websockets`, re-attempting up to five
        times on connection failure with a one second back-off. Each frame
        is parsed as a :class:`DataPackageModel`; if its status is in
        ``valid_data_status`` the visualizer schedules an async
        :meth:`add_points` call to pull the newest samples.
        """
        LOGGER.info(f" ... sample visualizer subscribing to: {self.data_url}")
        retry_limit = 5
        for _ in range(retry_limit):
            try:
                async with websockets.connect(self.data_url) as ws:
                    self.IOloop_data_run = True
                    while self.IOloop_data_run:
                        try:
                            datapackage = DataPackageModel(
                                **json.loads(await ws.recv())
                            )
                            datastatus = datapackage.datamodel.status
                            if datastatus in valid_data_status:
                                self.vis.doc.add_next_tick_callback(
                                    async_partial(self.add_points)
                                )
                        except Exception:
                            self.IOloop_data_run = False
                    await ws.close()
                    self.IOloop_data_run = False
            except Exception:
                LOGGER.error(
                    f"failed to subscribe to {self.data_url} trying again in 1sec",
                    exc_info=True,
                )
                await asyncio.sleep(1)
            if not self.IOloop_data_run:
                LOGGER.info("IOloop closed")
                break

    def reset_plot(self):
        """Schedule a fresh SAMPLE sample query on the next document tick."""
        # copy old data to "prev" plot
        self.vis.doc.add_next_tick_callback(partial(self.add_points))
