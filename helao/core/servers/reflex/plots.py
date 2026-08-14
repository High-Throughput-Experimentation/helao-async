"""The HELAO plot facade over the ``xy`` charting library.

This is the only module in the repository that imports xy's charting API.
Every chart in the Reflex UI stack is built through one of the four functions
here, so an alpha-stage upstream change is confined to a single file.

Functions take plain numpy arrays, never buffers, so they are testable with
synthetic data and no ingest layer present. Each builds an ``xy`` figure,
splits it into a small JSON spec plus raw column buffers, parks the buffers in
the process-wide store, and returns the Reflex component bound to both.
"""

__all__ = [
    "PlotBackendError",
    "STORE",
    "ChartPayload",
    "layout_token",
    "chart",
    "traces",
    "TRACE_KINDS",
    "time_series",
    "spectra",
    "scatter_map",
    "histogram",
]

import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from helao.ui.shared.palette import SERIES
from helao.core.servers.reflex.xy_component import (
    BUFFER_ROUTE_PREFIX,
    BufferStore,
    xy_chart,
)


class PlotBackendError(RuntimeError):
    """Raised when the xy backend is missing or unusable."""


try:
    import xy
except Exception as exc:  # pragma: no cover - import-time environment failure
    raise PlotBackendError(
        "the xy charting backend is unavailable; the Reflex UI stack cannot "
        f"start. Install it with `pip install xy==0.0.5`. Underlying error: {exc}"
    ) from exc

#: Process-wide store the buffer route serves from. Task 6 hands the router
#: built over this store to ``rx.App(api_transformer=...)``.
STORE = BufferStore()

#: Reused across series so panel colors stay stable between renders.
#: 10 entries (`SERIES`), up from the 8-entry tuple this replaces, so the
#: `idx % len(PALETTE)` wrap-around now lands on `cyan-600` (idx 8) and
#: `fuchsia-600` (idx 9) instead of repeating red -- cosmetic, and only
#: reachable by a chart with >= 9 traces (spec: "Qualitative series palette").
PALETTE = SERIES


def _as_float_array(values) -> np.ndarray:
    """Coerce ``values`` to a 1-D float64 array."""
    return np.asarray(values, dtype=np.float64).ravel()


#: Below this, an "epoch" column is not an epoch (1973), and rebasing it would
#: wreck it. Guards a panel that declares x_is_epoch but streams elapsed time.
_EPOCH_FLOOR = 1e8


def _rebase_epoch(xs: np.ndarray) -> np.ndarray:
    """Rebase epoch seconds to seconds since local midnight.

    xy encodes every column as f32, and f32 spacing near 1.75e9 is **128
    seconds**: a minute of 10 Hz telemetry collapsed onto two distinct x
    positions, which draws as a blank chart whose axis keeps widening. Under
    ~1e5 the spacing is ~8 ms instead.

    Local midnight specifically, and taken from the window's first sample. xy
    formats time axes with ``getUTC*`` and epoch 0 *is* midnight, so seconds
    since local midnight render as local clock time -- what a wall clock in the
    lab reads. Values past 86400 keep formatting correctly (86400 is 00:00:00
    the next day), so a window spanning midnight stays continuous instead of
    wrapping to zero.

    The one inaccuracy left: a window spanning a DST transition keeps the offset
    from its first sample, so labels after the change are an hour out. Twice a
    year, only while such a window is on screen.

    Args:
        xs: The x column, epoch seconds.

    Returns:
        np.ndarray: Rebased, or ``xs`` unchanged when it holds no finite value
        that looks like an epoch.
    """
    finite = xs[np.isfinite(xs)]
    if finite.size == 0 or float(finite[0]) < _EPOCH_FLOOR:
        return xs
    stamp = time.localtime(float(finite[0]))
    midnight = time.mktime(
        # -1 for isdst: let mktime resolve which offset applied on that date.
        (stamp.tm_year, stamp.tm_mon, stamp.tm_mday, 0, 0, 0, 0, 0, -1)
    )
    return xs - midnight


def _finite_pairs(x: np.ndarray, y: np.ndarray) -> tuple:
    """Drop index positions where either array is not finite."""
    if x.size == 0 or y.size == 0:
        return x, y
    keep = np.isfinite(x) & np.isfinite(y)
    return x[keep], y[keep]


@dataclass(frozen=True)
class ChartPayload:
    """What a panel assigns into state to drive a chart.

    Attributes:
        spec: Small data-less chart spec. Rides a Reflex var.
        buffer_url: Route the browser fetches column buffers from.
        layout: Token identifying the trace set. A change means the chart must
            be rebuilt rather than updated in place.
    """

    spec: dict
    buffer_url: str
    layout: str


def layout_token(spec: dict) -> str:
    """Summarize a spec's trace set as a short stable string.

    xy's in-place update path swaps column buffers for existing traces; it
    cannot add or remove one. A live HELAO stream does exactly that -- a
    simulator starts publishing ``series_4`` and the panel gains a line -- so
    the browser needs to know when an update is no longer applicable and the
    view has to be rebuilt from scratch.

    Args:
        spec: A spec from ``Figure.build_payload_split``.

    Returns:
        str: Equal for two specs with the same traces in the same order.
    """
    traces = spec.get("traces") or []
    return "|".join(f"{t.get('id')}:{t.get('kind')}:{t.get('name')}" for t in traces)


def _publish(figure, panel_id: str, version: int) -> ChartPayload:
    """Split a figure, park its buffers, and return the state payload.

    Args:
        figure: The assembled ``xy`` chart composition (an ``xy.chart(...)``
            result). ``xy.chart`` returns a ``Chart`` component, which
            composes its marks/axes children into the data-less ``Figure``
            lazily via ``.figure()`` — that ``Figure`` is what carries
            ``build_payload_split``, not the ``Chart`` itself.
        panel_id: Stable identity for this panel across re-renders.
        version: Monotonic token; the browser refetches when it changes.

    Returns:
        ChartPayload: Assign this into the panel's state vars.
    """
    spec, buffers = figure.figure().build_payload_split()
    # The browser applies an update only when ``spec.append.seq`` advances:
    # xy's change handler starts with `if (!spec.append) return`, and
    # ``build_payload_split`` leaves ``append`` unset. Without this the chart
    # paints its first frame and then never moves again, however often the
    # buffers change.
    #
    # Declaring every trace affected is correct here because these payloads
    # carry full canonical columns, exactly like the ones ``Figure.append``
    # emits -- xy's own streaming path re-sends whole columns rather than
    # deltas, and the client replaces the affected traces' data with them.
    spec["append"] = {
        "seq": int(version),
        "affected": [t.get("id") for t in (spec.get("traces") or [])],
    }
    STORE.put(panel_id, version, buffers)
    return ChartPayload(
        spec=spec,
        buffer_url=f"{BUFFER_ROUTE_PREFIX}/{panel_id}?v={version}",
        layout=layout_token(spec),
    )


def chart(spec_var, url_var, layout_var, *, height: int = 320, on_select=None):
    """Bind a chart component to three Reflex state vars.

    Called once from a panel's ``build``. The panel's ``pull`` then assigns
    fresh :class:`ChartPayload` values into the three vars, and the browser
    follows.

    Args:
        spec_var: Reflex var holding :attr:`ChartPayload.spec`.
        url_var: Reflex var holding :attr:`ChartPayload.buffer_url`.
        layout_var: Reflex var holding :attr:`ChartPayload.layout`. When it
            changes the browser rebuilds the chart instead of updating it.
        height: Chart height in pixels.
        on_select: Optional Reflex event handler for selection.

    Returns:
        An ``rx.Component``.
    """
    # Returned unwrapped. A box around this reserving the same height did stop
    # charts overlapping, but it also truncated them -- the y axis gutter fell
    # outside it, so ticks, labels and the axis title went missing. The height
    # reservation now lives on the host div itself (minHeight plus
    # flex-shrink: 0 in the shim's JSX), which is both the element that
    # collapsed and the element xy draws into.
    return xy_chart(
        spec=spec_var,
        buffer_url=url_var,
        layout=layout_var,
        height=f"{height}px",
        on_select=on_select,
    )


def _chart(marks, axes) -> Any:
    """Assemble a chart that sizes itself from its container.

    ``xy.chart`` defaults to a fixed 900x420 spec, and the renderer uses those
    numbers literally: it built a 420px-tall root inside whatever div it was
    given, overflowed it, and the card's ``overflow: hidden`` clipped the
    bottom -- so the x axis simply vanished, while nothing about the data path
    looked wrong. ``"100%"`` selects xy's fluid path, where it measures the
    element it is mounted into. That element already carries an explicit height
    from :func:`chart`, which makes the host div the single place a chart's size
    is decided rather than a figure spec and a CSS rule that can disagree.
    """
    return xy.chart(*marks, *axes, width="100%", height="100%")


def _axes(x_label: str, y_label: str, x_is_epoch: bool) -> list:
    """Build the axis child components.

    Epoch seconds get ``type_="time"`` plus a ``%H:%M:%S`` format string, to
    match the ``DatetimeTickFormatter`` the Bokeh visualizers use. xy's axis
    builders take ``type_``/``format`` (verified in the Task 0 API note's
    probe of ``xy._figure.Figure.set_axis``); there is no ``scale`` or
    ``tick_format`` kwarg.
    """
    x_kwargs: dict[str, Any] = {"label": x_label}
    if x_is_epoch:
        x_kwargs["type_"] = "time"
        x_kwargs["format"] = "%H:%M:%S"
    return [xy.x_axis(**x_kwargs), xy.y_axis(label=y_label)]


def time_series(
    x,
    series: dict,
    *,
    x_label: str = "",
    y_label: str = "",
    x_is_epoch: bool = True,
    panel_id: str = "plot",
    version: int = 0,
):
    """Render one or more line traces against a shared x axis.

    Args:
        x: Shared x values. Epoch seconds when ``x_is_epoch`` is ``True``.
        series: Mapping of legend label to equal-length y values.
        x_label: X axis label.
        y_label: Y axis label.
        x_is_epoch: Format the x axis as ``HH:MM:SS``.
        panel_id: Stable panel identity for the buffer route.
        version: Monotonic data version; the browser refetches when it changes.

    Returns:
        ChartPayload: Assign into the panel state vars bound by :func:`chart`.
        An empty ``x`` yields a valid empty chart.

    Raises:
        ValueError: If a series length does not match ``len(x)``.
    """
    xs = _as_float_array(x)
    if x_is_epoch:
        # Must happen before the marks are built: f32 cannot carry an epoch.
        xs = _rebase_epoch(xs)
    marks = []
    for idx, (label, values) in enumerate(series.items()):
        ys = _as_float_array(values)
        # Checked unconditionally: gating on `xs.size` would skip validation
        # exactly when x is empty, letting a non-empty series through silently.
        if ys.size != xs.size:
            raise ValueError(
                f"series '{label}' has length {ys.size}, expected {xs.size}"
            )
        fx, fy = _finite_pairs(xs, ys)
        # Kept even with nothing finite in this window. Dropping it changed the
        # trace set, so `layout_token` changed, so the browser tore the view down
        # and rebuilt it -- and a sensor that goes briefly non-finite did that on
        # alternating ticks, which is a line that appears and disappears as you
        # watch. xy is happy with a zero-length trace: the column is empty and
        # the axis range comes from the traces that do have points.
        marks.append(xy.line(x=fx, y=fy, name=label, color=PALETTE[idx % len(PALETTE)]))
    figure = _chart(marks, _axes(x_label, y_label, x_is_epoch))
    return _publish(figure, panel_id, version)


#: Mark builders the data browser's trace-type control selects between.
#: Matches the Bokeh data browser exactly; xy also ships ``step``, but adding it
#: here would make the port a feature change rather than a re-rendering.
TRACE_KINDS = {"line": "line", "scatter": "scatter"}


def traces(
    series,
    *,
    kind: str = "line",
    x_label: str = "",
    y_label: str = "",
    panel_id: str = "traces",
    version: int = 0,
):
    """Render traces that each carry their own x values.

    :func:`time_series` and :func:`spectra` both take a single ``x`` shared by
    every series. The data browser overlays datasets read from unrelated files,
    so each has its own x column and a shared axis would misalign them.

    Args:
        series: Sequence of ``{"label": str, "x": array, "y": array}``.
        kind: ``"line"`` or ``"scatter"``.
        x_label: X axis label.
        y_label: Y axis label.
        panel_id: Stable panel identity for the buffer route.
        version: Monotonic data version; the browser refetches when it changes.

    Returns:
        ChartPayload: Assign into the panel state vars bound by :func:`chart`.
        A trace with no finite points is kept as an empty trace rather than
        dropped, so the trace set -- and with it ``layout_token`` -- does not
        change from tick to tick. An empty ``series`` yields a valid empty
        chart.

    Raises:
        ValueError: If ``kind`` is unknown, or a trace's x and y differ in
            length.
    """
    if kind not in TRACE_KINDS:
        raise ValueError(
            f"unknown trace kind {kind!r}; expected one of {sorted(TRACE_KINDS)}"
        )
    builder = getattr(xy, TRACE_KINDS[kind])
    marks = []
    for idx, item in enumerate(series):
        xs = _as_float_array(item["x"])
        ys = _as_float_array(item["y"])
        # Checked before the finite filter: a length mismatch is a caller bug,
        # and quietly using the shorter of the two would hide it behind a plot
        # that looks entirely plausible.
        if xs.size != ys.size:
            raise ValueError(
                f"trace '{item['label']}' has x length {xs.size} "
                f"and y length {ys.size}"
            )
        fx, fy = _finite_pairs(xs, ys)
        # Kept even when empty, so the trace set stays put; see time_series.
        marks.append(
            builder(
                x=fx,
                y=fy,
                name=item["label"],
                color=PALETTE[idx % len(PALETTE)],
            )
        )
    figure = _chart(marks, _axes(x_label, y_label, False))
    return _publish(figure, panel_id, version)


def spectra(
    x,
    traces: dict,
    *,
    x_label: str = "",
    y_label: str = "",
    panel_id: str = "spectra",
    version: int = 0,
):
    """Render many traces sharing one linear x axis (wavelength, energy).

    Same shape as :func:`time_series` but without epoch formatting, kept
    separate so spectrometer panels read clearly and so the two can diverge
    (trace limits, downsampling) without disturbing each other.

    Args:
        x: Shared x values.
        traces: Mapping of legend label to equal-length y values.
        x_label: X axis label.
        y_label: Y axis label.
        panel_id: Stable panel identity for the buffer route.
        version: Monotonic data version.

    Returns:
        ChartPayload: Assign into the panel state vars bound by :func:`chart`.
    """
    return time_series(
        x,
        traces,
        x_label=x_label,
        y_label=y_label,
        x_is_epoch=False,
        panel_id=panel_id,
        version=version,
    )


def scatter_map(
    x,
    y,
    *,
    values=None,
    x_label: str = "",
    y_label: str = "",
    panel_id: str = "scatter",
    version: int = 0,
):
    """Render a 2-D point cloud, optionally colored and selectable.

    Backs plate maps and any other spatial sample view.

    Args:
        x: Point x coordinates.
        y: Point y coordinates.
        values: Optional per-point scalar driving color.
        x_label: X axis label.
        y_label: Y axis label.
        panel_id: Stable panel identity for the buffer route.
        version: Monotonic data version.

    Returns:
        ChartPayload: Assign into the panel state vars bound by :func:`chart`.

    Raises:
        ValueError: If ``x`` and ``y`` differ in length, or ``values`` does not
            match them.
    """
    xs = _as_float_array(x)
    ys = _as_float_array(y)
    # Checked before the finite filter, as in `traces`: a length mismatch is a
    # caller bug and must not be hidden by dropping points.
    if xs.size != ys.size:
        raise ValueError(f"x has length {xs.size} but y has length {ys.size}")
    vs = None
    if values is not None:
        vs = _as_float_array(values)
        if vs.size != xs.size:
            raise ValueError(f"values has length {vs.size}, expected {xs.size}")
    # Non-finite points are dropped here, as `time_series` and `traces` already
    # do. This function skipped it, and a NaN in `values` reaches the renderer
    # as a color: the browser reports "Expected color but found 'NaN'" and the
    # chart is left in a state a plain blank canvas does not explain. The mask
    # spans all three arrays, because color is per point and filtering them
    # independently would shift colors onto the wrong points.
    keep = np.isfinite(xs) & np.isfinite(ys)
    if vs is not None:
        keep &= np.isfinite(vs)
    xs, ys = xs[keep], ys[keep]
    mark_kwargs: dict[str, Any] = {"x": xs, "y": ys}
    mark_kwargs["color"] = vs[keep] if vs is not None else PALETTE[0]
    marks = [xy.scatter(**mark_kwargs)] if xs.size else []
    figure = _chart(marks, _axes(x_label, y_label, False))
    return _publish(figure, panel_id, version)


def histogram(
    values_by_label: dict,
    *,
    bins: int = 100,
    value_range=None,
    x_label: str = "",
    y_label: str = "density",
    panel_id: str = "histogram",
    version: int = 0,
):
    """Render one or more density histograms using xy's native ``hist`` mark.

    Args:
        values_by_label: Mapping of legend label to raw sample values.
        bins: Number of histogram bins.
        value_range: Optional ``(low, high)`` range.
        x_label: X axis label.
        y_label: Y axis label.
        panel_id: Stable panel identity for the buffer route.
        version: Monotonic data version.

    Returns:
        ChartPayload: Assign into the panel state vars bound by :func:`chart`.
        Empty or all-non-finite series are skipped.
    """
    marks = []
    for idx, (label, values) in enumerate(values_by_label.items()):
        arr = _as_float_array(values)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            continue
        kwargs = {
            "values": arr,
            "bins": bins,
            "name": f"{label} n={arr.size:d}",
            "color": PALETTE[idx % len(PALETTE)],
            "density": True,
        }
        if value_range is not None:
            kwargs["range"] = value_range
        marks.append(xy.hist(**kwargs))
    figure = _chart(marks, _axes(x_label, y_label, False))
    return _publish(figure, panel_id, version)
