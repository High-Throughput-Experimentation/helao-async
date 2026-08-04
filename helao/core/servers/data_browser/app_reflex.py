"""Reflex rendering of the data browser.

A second UI over the same logic the Bokeh browser uses: ``sources`` builds the
index, ``state`` turns index rows into datasets, traces and summary rows, and
``readers`` reads files. None of those modules know this exists, and none of
them may be changed to suit it -- ``app.py`` is still live beside this.

The parts that can be wrong live in module-level functions rather than on the
state class, because ``rx.State`` cannot be instantiated outside a running app.
The state class is then only var assignment and cadence.
"""

__all__ = [
    "IndexCache",
    "INDEX_CACHE",
    "options_for_group",
    "scan_index",
    "filter_index",
    "index_rows",
    "cap_rows",
    "load_positions",
    "axis_options",
    "chart_series",
    "is_numeric",
    "summary_rows",
    "dataset_rows",
    "BrowserState",
    "build_page",
]

import threading

import numpy as np
import reflex as rx

from helao.core.servers.data_browser import sources
from helao.core.servers.data_browser import state as dbstate
from helao.core.servers.data_browser.app import FILTER_COLS, INDEX_TABLE_COLS
from helao.core.servers.reflex import plots
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Trailing points kept per trace. Mirrors the Bokeh browser's ``max_points``
#: server param default.
DEFAULT_MAX_POINTS = 50000

#: Index rows rendered at once. The checkbox table is one component per cell,
#: so a several-thousand-row scan would build a browser-hostile DOM. The page
#: says when it has capped, rather than quietly showing a prefix.
MAX_INDEX_ROWS = 500


class IndexCache:
    """Process-side ``session_token -> index DataFrame`` map.

    The index runs to thousands of rows: bulk data, which the parent spec keeps
    off Reflex's JSON state channel. It is keyed per session so two tabs
    scanning different sources cannot overwrite each other.
    """

    def __init__(self):
        """Create an empty cache."""
        self._lock = threading.Lock()
        self._frames: dict = {}

    def put(self, token: str, df) -> None:
        """Store the newest scan for a session."""
        with self._lock:
            self._frames[token] = df

    def get(self, token: str):
        """Return a session's scan, or ``None`` if it has not scanned."""
        with self._lock:
            return self._frames.get(token)

    def drop(self, token: str) -> None:
        """Forget a session, e.g. when its page unmounts."""
        with self._lock:
            self._frames.pop(token, None)


#: Process-wide cache the page reads through.
INDEX_CACHE = IndexCache()


def options_for_group(group: str) -> list:
    """Source names in a group.

    Args:
        group: Key of :data:`sources.GROUPS`.

    Returns:
        list: Source names, empty for an unknown group. Empty rather than
        raising: a reconnecting session can carry a stale group string, and a
        500 on the page is a worse answer than an empty select.
    """
    return list(sources.GROUPS.get(group, []))


def scan_index(root: str, source: str, date_start, date_end):
    """Build the candidate-dataset index.

    Args:
        root: HELAO output root.
        source: Source name.
        date_start: ``YY.WW/MMDD`` lower bound, or ``None``.
        date_end: Upper bound, or ``None``.

    Returns:
        tuple: ``(DataFrame, "")`` on success, ``(None, message)`` on failure.
        Failures are returned rather than raised: this runs inside a background
        event, where an exception is swallowed into the log and the page just
        sits there looking like a hang.
    """
    try:
        return sources.get_index(root, source, date_start, date_end), ""
    except Exception as exc:
        LOGGER.warning(f"data browser scan failed for {source!r}: {exc}")
        return None, f"scan failed for {source}: {exc}"


def filter_index(index_df, query: str):
    """Filter the index by a substring across :data:`FILTER_COLS`.

    Args:
        index_df: The scanned index, or ``None``.
        query: Free-text query; blank returns everything.

    Returns:
        The filtered DataFrame, or ``None`` when there is no index.
    """
    if index_df is None:
        return None
    needle = (query or "").strip().lower()
    if not needle:
        return index_df
    mask = (
        index_df[FILTER_COLS]
        .astype(str)
        .apply(lambda r: needle in " ".join(r.values).lower(), axis=1)
    )
    return index_df[mask]


def index_rows(index_df) -> list:
    """Render the index as table rows.

    Every cell is a string: Reflex serialises state to JSON, and a numpy bool
    or a NaN reaches the browser as garbage or breaks the encoder outright.

    Args:
        index_df: A scanned (and possibly filtered) index, or ``None``.

    Returns:
        list[list[str]]: One row per dataset, columns in
        :data:`INDEX_TABLE_COLS` order.
    """
    if index_df is None or not len(index_df):
        return []
    return [
        [str(row[col]) for col in INDEX_TABLE_COLS] for _, row in index_df.iterrows()
    ]


def cap_rows(rows: list, cap: int):
    """Limit rendered rows, reporting whether anything was withheld.

    Args:
        rows: All matching rows.
        cap: Maximum to render.

    Returns:
        tuple: ``(view, total, truncated)``. The caller shows ``total`` and
        ``truncated`` -- a capped table that does not say so reads as the whole
        result set.
    """
    return rows[:cap], len(rows), len(rows) > cap


def load_positions(index_df, positions):
    """Read the chosen index rows into datasets.

    Args:
        index_df: A scanned (and possibly filtered) index, or ``None``.
        positions: Integer positions into ``index_df``.

    Returns:
        tuple: ``(datasets, skipped)``, where ``skipped`` is
        ``[(label, reason)]``. Unreadable and unavailable files are reported,
        never silently dropped.
    """
    if index_df is None:
        return [], []
    return dbstate.load_selected(index_df.reset_index(drop=True), positions)


def axis_options(selected) -> list:
    """Column names available across the selected datasets."""
    return dbstate.available_columns(selected)


def is_numeric(values) -> bool:
    """Whether a column can be plotted.

    HELAO datasets carry string columns freely -- an orchestrator host, a
    status message, a sample label sit beside the numeric traces. Handing one
    to the plot facade raises ``could not convert string to float`` from inside
    the render, which takes down the whole chart rather than one trace.

    Args:
        values: A dataset column.

    Returns:
        bool: ``True`` when every value coerces to float.
    """
    try:
        np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError):
        return False
    return True


def chart_series(selected, xcol: str, ycol: str, max_points: int):
    """Build :func:`plots.traces` input from the selected datasets.

    Args:
        selected: ``SelectedDataset`` list.
        xcol: Chosen x column.
        ycol: Chosen y column.
        max_points: Downsampling cap per trace.

    Returns:
        tuple: ``(series, skipped)``. ``series`` is ``{"label", "x", "y"}`` per
        plottable dataset; ``skipped`` is ``[(label, reason)]``. Datasets are
        skipped for missing the chosen columns -- normal when overlaying files
        from unrelated runs -- or for holding non-numeric values there, which
        would otherwise abort the entire chart.
    """
    if not xcol or not ycol:
        return [], []
    series, skipped = [], []
    for ds in selected:
        trace = dbstate.build_trace(ds, xcol, ycol)
        if trace is None:
            skipped.append((ds.label, f"has no {xcol}/{ycol} columns"))
            continue
        if not is_numeric(trace["x"]) or not is_numeric(trace["y"]):
            skipped.append((ds.label, f"{xcol}/{ycol} are not numeric"))
            continue
        trace = dbstate.downsample(trace, max_points)
        series.append({"label": ds.label, "x": trace["x"], "y": trace["y"]})
    return series, skipped


def summary_rows(selected, xcol: str, ycol: str) -> list:
    """One summary-table row per selected dataset, as strings."""
    return [
        [str(dbstate.summary_row(ds, xcol, ycol)[col]) for col in dbstate.SUMMARY_COLS]
        for ds in selected
    ]


def dataset_rows(ds):
    """Render one dataset's raw columns as a table.

    Args:
        ds: A ``SelectedDataset``, or ``None``.

    Returns:
        tuple: ``(headers, rows)``, both empty when ``ds`` is ``None``.
    """
    if ds is None:
        return [], []
    headers = list(ds.data.keys())
    if not headers:
        return [], []
    length = min(len(ds.data[h]) for h in headers)
    return headers, [[str(ds.data[h][i]) for h in headers] for i in range(length)]


def _config_root() -> str:
    """HELAO output root from the installed global config."""
    from helao.helpers import config_loader

    cfg = config_loader.CONFIG or {}
    return str(cfg.get("root", ""))


class BrowserState(rx.State):
    """Page state for the data browser.

    A plain state, not a mixin: mixins exist for ``make_panel_state``, which
    mints one class per action server so their vars cannot be shared. This is
    one page with one state.
    """

    # Element types are annotated, not bare `list`: rx.foreach cannot iterate
    # a var whose element type is unknown, and the frontend build fails with
    # ForeachVarError rather than anything visible at import time.

    #: Selected datasets. The leading underscore makes this a Reflex *backend*
    #: var: it stays server-side and is never serialised to the client. That is
    #: required, not cosmetic -- these hold whole data files, and an ordinary
    #: annotated attribute would become a client var and fail to encode.
    _datasets: list = []

    group: str = "RUNS"
    source: str = ""
    source_options: list[str] = []
    date_start: str = ""
    date_end: str = ""
    index_filter: str = ""
    index_rows_view: list[list[str]] = []
    selected_positions: list[int] = []
    index_total: int = 0
    index_truncated: bool = False
    status: str = ""
    error: str = ""
    scanning: bool = False
    xcol: str = ""
    ycol: str = ""
    axis_choices: list[str] = []
    trace_kind: str = "line"
    chart_spec: dict = {}
    chart_url: str = ""
    chart_layout: str = ""
    version: int = 0
    summary_view: list[list[str]] = []

    def panel_key(self) -> str:
        """Session-scoped buffer-store key.

        The store holds one frame per key while ``version`` is per-session
        state, so a shared key would 404 two tabs into frozen charts.
        """
        return f"browser-{self.router.session.client_token}"

    @rx.event
    def on_mount(self):
        """Seed the source options from the default group."""
        self.source_options = options_for_group(self.group)
        if self.source_options and self.source not in self.source_options:
            self.source = self.source_options[0]

    @rx.event
    def on_group(self, value: str):
        """Switch group and reset the source to that group's first entry."""
        self.group = value
        self.source_options = options_for_group(value)
        self.source = self.source_options[0] if self.source_options else ""

    @rx.event
    def on_source(self, value: str):
        """Select the source to scan."""
        self.source = value

    @rx.event
    def on_date_start(self, value: str):
        """Set the lower date bound."""
        self.date_start = value

    @rx.event
    def on_date_end(self, value: str):
        """Set the upper date bound."""
        self.date_end = value

    @rx.event
    def on_trace_kind(self, value: str):
        """Switch between line and scatter."""
        self.trace_kind = value
        self._rebuild()

    @rx.event
    def on_xcol(self, value: str):
        """Choose the x column."""
        self.xcol = value
        self._rebuild()

    @rx.event
    def on_ycol(self, value: str):
        """Choose the y column."""
        self.ycol = value
        self._rebuild()

    @rx.event
    def on_filter(self, value: str):
        """Filter the index table."""
        self.index_filter = value
        self._refresh_index()

    @rx.event
    def toggle_position(self, position: int):
        """Check or uncheck one index row.

        Reflex's data_table has no row-selection callback, so selection is an
        explicit checkbox column rather than a table feature. Positions index
        into the *filtered* frame, which is what ``load_positions`` takes.
        """
        if position in self.selected_positions:
            self.selected_positions = [
                p for p in self.selected_positions if p != position
            ]
        else:
            self.selected_positions = self.selected_positions + [position]

    @rx.event(background=True)
    async def scan(self):
        """Index the selected source.

        Background because ``sources.get_index`` walks the run tree, which on a
        station's output root takes long enough to freeze a synchronous handler
        outright.
        """
        async with self:
            self.scanning = True
            self.error = ""
            self.status = f"scanning {self.source}..."
            root = _config_root()
            source, start, end = self.source, self.date_start, self.date_end
            token = self.router.session.client_token

        df, error = scan_index(root, source, start.strip() or None, end.strip() or None)

        async with self:
            self.scanning = False
            if error:
                self.error = error
                self.status = ""
                INDEX_CACHE.drop(token)
                self.index_rows_view = []
                self.index_total = 0
                self.index_truncated = False
                return
            INDEX_CACHE.put(token, df)
            self.status = f"indexed {len(df)} dataset(s) from {source}"
            self._refresh_index()

    @rx.event(background=True)
    async def add_selected(self):
        """Load the checked index rows and add them to the plot.

        Background because each dataset is a file read.
        """
        async with self:
            token = self.router.session.client_token
            positions = list(self.selected_positions)
            query = self.index_filter
        df = filter_index(INDEX_CACHE.get(token), query)
        datasets, skipped = load_positions(df, positions)

        async with self:
            self._datasets = self._datasets + datasets
            # Named, not silently dropped: an omitted trace with no explanation
            # is the worst way to present an unreadable file.
            self.error = (
                "; ".join(f"skipped {lbl}: {why}" for lbl, why in skipped)
                if skipped
                else ""
            )
            self._refresh_axes()
            self._rebuild()

    @rx.event
    def clear_plot(self):
        """Drop every selected dataset."""
        self._datasets = []
        self.error = ""
        self._refresh_axes()
        self._rebuild()

    @rx.event
    def on_unmount(self):
        """Release this session's index and chart frame."""
        token = self.router.session.client_token
        INDEX_CACHE.drop(token)
        plots.STORE.drop(f"browser-{token}")

    # -- internals -------------------------------------------------------

    def _refresh_index(self):
        """Re-render the index table under the current filter."""
        token = self.router.session.client_token
        filtered = filter_index(INDEX_CACHE.get(token), self.index_filter)
        view, total, truncated = cap_rows(index_rows(filtered), MAX_INDEX_ROWS)
        self.index_rows_view = view
        self.index_total = total
        self.index_truncated = truncated
        # Positions index into the filtered frame, so a changed filter
        # invalidates every one of them; keeping them would add whichever rows
        # now happen to sit at those offsets.
        self.selected_positions = []

    def _refresh_axes(self):
        """Recompute axis choices, keeping the current pick when still valid."""
        self.axis_choices = axis_options(self._datasets)
        if not self.axis_choices:
            self.xcol, self.ycol = "", ""
            return
        if self.xcol not in self.axis_choices:
            self.xcol = self.axis_choices[0]
        if self.ycol not in self.axis_choices:
            self.ycol = (
                self.axis_choices[1]
                if len(self.axis_choices) > 1
                else self.axis_choices[0]
            )

    def _rebuild(self):
        """Recompute the chart payload and the summary table."""
        series, unplottable = chart_series(
            self._datasets, self.xcol, self.ycol, DEFAULT_MAX_POINTS
        )
        self.version += 1
        payload = plots.traces(
            series,
            kind=self.trace_kind,
            x_label=self.xcol,
            y_label=self.ycol,
            panel_id=self.panel_key(),
            version=self.version,
        )
        self.chart_spec = payload.spec
        self.chart_url = payload.buffer_url
        self.chart_layout = payload.layout
        self.summary_view = summary_rows(self._datasets, self.xcol, self.ycol)
        self.status = f"{len(self._datasets)} dataset(s) selected"
        # Said out loud: a dataset that silently never appears on the chart is
        # indistinguishable from a broken plot.
        if unplottable:
            self.error = "; ".join(f"{lbl}: {why}" for lbl, why in unplottable)


def build_page():
    """Render the data browser page.

    Returns:
        rx.Component: The page body.
    """
    controls = rx.hstack(
        rx.select(
            list(sources.GROUPS.keys()),
            value=BrowserState.group,
            on_change=BrowserState.on_group,
            width="9em",
        ),
        rx.select(
            BrowserState.source_options,
            value=BrowserState.source,
            on_change=BrowserState.on_source,
            width="12em",
        ),
        rx.input(
            placeholder="From (YY.WW/MMDD)",
            value=BrowserState.date_start,
            on_change=BrowserState.on_date_start,
            width="11em",
        ),
        rx.input(
            placeholder="To (YY.WW/MMDD)",
            value=BrowserState.date_end,
            on_change=BrowserState.on_date_end,
            width="11em",
        ),
        rx.button("Scan", on_click=BrowserState.scan, loading=BrowserState.scanning),
        spacing="3",
        align="end",
        width="100%",
    )

    # An explicit checkbox column, not rx.data_table: gridjs exposes no
    # row-selection callback, and the Bokeh browser's whole workflow is
    # "tick several rows, then Add to plot". A read-only table would strand it.
    index_box = rx.vstack(
        rx.input(
            placeholder="Filter index",
            value=BrowserState.index_filter,
            on_change=BrowserState.on_filter,
            width="100%",
        ),
        rx.cond(
            BrowserState.index_truncated,
            rx.text(
                f"showing the first {MAX_INDEX_ROWS} of ",
                BrowserState.index_total,
                " matches -- narrow the filter to reach the rest",
                size="2",
                class_name="text-amber-700",
            ),
        ),
        rx.scroll_area(
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell(""),
                        *[rx.table.column_header_cell(col) for col in INDEX_TABLE_COLS],
                    )
                ),
                rx.table.body(
                    rx.foreach(
                        BrowserState.index_rows_view,
                        lambda row, idx: rx.table.row(
                            rx.table.cell(
                                rx.checkbox(
                                    checked=BrowserState.selected_positions.contains(
                                        idx
                                    ),
                                    on_change=BrowserState.toggle_position(idx),
                                )
                            ),
                            rx.foreach(row, lambda cell: rx.table.cell(cell)),
                        ),
                    )
                ),
                width="100%",
                size="1",
            ),
            type="auto",
            scrollbars="vertical",
            height="20em",
        ),
        rx.hstack(
            rx.button("Add to plot", on_click=BrowserState.add_selected),
            rx.button("Clear plot", on_click=BrowserState.clear_plot),
            spacing="3",
        ),
        width="100%",
        spacing="2",
    )

    plot_tab = rx.vstack(
        rx.hstack(
            rx.select(
                BrowserState.axis_choices,
                value=BrowserState.xcol,
                on_change=BrowserState.on_xcol,
                width="12em",
            ),
            rx.select(
                BrowserState.axis_choices,
                value=BrowserState.ycol,
                on_change=BrowserState.on_ycol,
                width="12em",
            ),
            rx.select(
                list(plots.TRACE_KINDS),
                value=BrowserState.trace_kind,
                on_change=BrowserState.on_trace_kind,
                width="9em",
            ),
            spacing="3",
        ),
        # Bound once. The payload is produced in _rebuild, per interaction.
        plots.chart(
            BrowserState.chart_spec,
            BrowserState.chart_url,
            BrowserState.chart_layout,
            height=420,
        ),
        width="100%",
        spacing="3",
    )

    table_tab = rx.data_table(
        data=BrowserState.summary_view,
        columns=list(dbstate.SUMMARY_COLS),
        pagination=True,
        search=False,
        sort=True,
    )

    return rx.vstack(
        controls,
        rx.cond(
            BrowserState.error != "",
            rx.text(BrowserState.error, class_name="text-red-600"),
        ),
        rx.text(BrowserState.status, size="2"),
        index_box,
        rx.tabs.root(
            rx.tabs.list(
                rx.tabs.trigger("Plot", value="plot"),
                rx.tabs.trigger("Table", value="table"),
            ),
            rx.tabs.content(plot_tab, value="plot"),
            rx.tabs.content(table_tab, value="table"),
            default_value="plot",
            width="100%",
        ),
        width="100%",
        spacing="4",
        padding_x="1em",
        on_mount=BrowserState.on_mount,
        on_unmount=BrowserState.on_unmount,
    )
