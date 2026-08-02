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
    "summary_rows",
    "dataset_rows",
]

import threading

from helao.core.servers.data_browser import sources
from helao.core.servers.data_browser import state as dbstate
from helao.core.servers.data_browser.app import FILTER_COLS, INDEX_TABLE_COLS
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


def chart_series(selected, xcol: str, ycol: str, max_points: int) -> list:
    """Build :func:`plots.traces` input from the selected datasets.

    Args:
        selected: ``SelectedDataset`` list.
        xcol: Chosen x column.
        ycol: Chosen y column.
        max_points: Downsampling cap per trace.

    Returns:
        list: ``{"label", "x", "y"}`` per dataset that has both columns.
        Datasets missing either are skipped -- overlaying files from unrelated
        runs means some will not share columns, which is normal.
    """
    if not xcol or not ycol:
        return []
    series = []
    for ds in selected:
        trace = dbstate.build_trace(ds, xcol, ycol)
        if trace is None:
            continue
        trace = dbstate.downsample(trace, max_points)
        series.append({"label": ds.label, "x": trace["x"], "y": trace["y"]})
    return series


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
