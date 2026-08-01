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
    "chart",
    "time_series",
    "spectra",
    "scatter_map",
    "histogram",
]

from dataclasses import dataclass
from typing import Any

import numpy as np

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
PALETTE = (
    "#d62728",
    "#1f77b4",
    "#2ca02c",
    "#ff7f0e",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
)


def _as_float_array(values) -> np.ndarray:
    """Coerce ``values`` to a 1-D float64 array."""
    return np.asarray(values, dtype=np.float64).ravel()


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
    """

    spec: dict
    buffer_url: str


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
    STORE.put(panel_id, version, buffers)
    return ChartPayload(
        spec=spec,
        buffer_url=f"{BUFFER_ROUTE_PREFIX}/{panel_id}?v={version}",
    )


def chart(spec_var, url_var, *, height: int = 320, on_select=None):
    """Bind a chart component to two Reflex state vars.

    Called once from a panel's ``build``. The panel's ``pull`` then assigns
    fresh :class:`ChartPayload` values into ``spec_var`` and ``url_var``, and
    the browser follows.

    Args:
        spec_var: Reflex var holding :attr:`ChartPayload.spec`.
        url_var: Reflex var holding :attr:`ChartPayload.buffer_url`.
        height: Chart height in pixels.
        on_select: Optional Reflex event handler for selection.

    Returns:
        An ``rx.Component``.
    """
    return xy_chart(
        spec=spec_var,
        buffer_url=url_var,
        height=f"{height}px",
        on_select=on_select,
    )


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
        if fx.size == 0:
            continue
        marks.append(xy.line(x=fx, y=fy, name=label, color=PALETTE[idx % len(PALETTE)]))
    figure = xy.chart(*marks, *_axes(x_label, y_label, x_is_epoch))
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
    if xs.size != ys.size:
        raise ValueError(f"x has length {xs.size} but y has length {ys.size}")
    mark_kwargs: dict[str, Any] = {"x": xs, "y": ys}
    if values is not None:
        vs = _as_float_array(values)
        if vs.size != xs.size:
            raise ValueError(f"values has length {vs.size}, expected {xs.size}")
        mark_kwargs["color"] = vs
    else:
        mark_kwargs["color"] = PALETTE[0]
    marks = [xy.scatter(**mark_kwargs)] if xs.size else []
    figure = xy.chart(*marks, *_axes(x_label, y_label, False))
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
    figure = xy.chart(*marks, *_axes(x_label, y_label, False))
    return _publish(figure, panel_id, version)
