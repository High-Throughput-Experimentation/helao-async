# helao/ui/reflex/spectra_page.py
"""What the plate-spectra pages (`/uvvis`, `/xafs`, `/xrds`) share.

Each page loads a selection of one technique's spectra for a plate and show

* a plate map coloured by each sample's mean y inside an x window set by two
  sliders (editable readouts, both starting at the grid midpoint),
* a histogram of those window means,
* the spectrum chart: the selection's average in grey with the window shaded
  over it, and clicked samples' spectra on top in their ring colours, and
* a details table for the clicked sample.

They differ in how a plate's spectra are found, how a selection is grouped,
which series are x and y, and what range the details table summarizes. Those
live in the page modules; everything else lives in :class:`SpectraPageState`.

**The state here is a Reflex mixin, and that is load-bearing** (see
``state.py``): vars declared on a concrete ``rx.State`` are shared by every
subclass, so two pages built on one concrete base would share one plate id.
Page states are ``class X(SpectraPageState, rx.State)``.
"""

from __future__ import annotations

from typing import ClassVar, Optional

import numpy as np
import reflex as rx

from helao.ui.reflex import plots
from helao.ui.reflex.composition import (
    CHART_HEIGHT,
    MAX_POINT_SCALE,
    SPECTRUM_HEIGHT,
    nearest_record,
)
from helao.ui.shared import spectra
from helao.ui.shared.composition import grouping
from helao.ui.shared.palette import (
    WINDOW_COLORMAP,
    reflex_muted_text_class,
    reflex_table_class,
)
from helao.ui.shared.platemap import _as_number


def _fmt(value) -> str:
    return f"{value:.6g}"


def detail_rows(
    record, x, y, lo: float, hi: float, *, x_unit: str, stats_range=None, decimals=1
) -> list:
    """The clicked sample's table: its window mean and range statistics.

    Args:
        stats_range: ``(lo, hi)`` the min/mean/max/stdev rows cover; ``None``
            means the window itself.
    """
    lo, hi = min(lo, hi), max(lo, hi)
    rows = [
        ["quantity", "value"],
        ["run_use", record.run_use or grouping.NO_RUN_USE],
        [
            f"window mean ({lo:.{decimals}f}-{hi:.{decimals}f} {x_unit}".rstrip() + ")",
            _fmt(spectra.window_mean(x, y, lo, hi)),
        ],
    ]
    r0, r1 = stats_range if stats_range is not None else (lo, hi)
    where = f"{r0:g}-{r1:g} {x_unit}" if stats_range is not None else "window"
    stats = spectra.range_stats(x, y, r0, r1)
    for name in ("min", "mean", "max", "stdev"):
        value = stats.get(name)
        rows.append([f"{name} ({where})", "-" if value is None else _fmt(value)])
    return rows


class SpectraPageState(rx.State, mixin=True):
    """Everything a plate-spectra page holds, except the spectra themselves."""

    #: Set by each page. ``STATS_RANGE`` ``None`` = statistics on the window.
    FILE_TYPE: ClassVar[str] = ""
    X_KEY: ClassVar[str] = ""
    Y_KEY: ClassVar[str] = ""
    X_LABEL: ClassVar[str] = ""
    Y_LABEL: ClassVar[str] = ""
    Y_NAME: ClassVar[str] = ""
    X_UNIT: ClassVar[str] = ""
    STATS_RANGE: ClassVar[Optional[tuple]] = None
    PANEL_PREFIX: ClassVar[str] = "spectra"
    #: Window slider step, and the decimals its readouts and labels show.
    SLIDER_STEP: ClassVar[float] = 0.5
    DECIMALS: ClassVar[int] = 1

    plate_id: str = ""
    status: str = ""
    error: str = ""
    platemap_note: str = ""

    #: The loaded grid's x range, and the window on it.
    wl_min: float = 0.0
    wl_max: float = 1.0
    wl_lo: float = 0.5
    wl_hi: float = 0.5
    wl_lo_text: str = ""
    wl_hi_text: str = ""

    overlay_spectra: bool = False
    point_scale: float = 1.0

    selected_label: str = ""
    detail_rows: list[list[str]] = []

    map_spec: dict = {}
    map_url: str = ""
    map_layout: str = ""
    hist_spec: dict = {}
    hist_url: str = ""
    hist_layout: str = ""
    spec_spec: dict = {}
    spec_url: str = ""
    spec_layout: str = ""

    version: int = 0

    #: Backend only; spectra are in `spectra`'s module cache.
    _records: list = []
    _pm_rows: list = []
    #: The records Plot loaded, and those of them on the plate map.
    _loaded: list = []
    _plotted: list = []
    _plotted_xs: list = []
    _plotted_ys: list = []
    #: Clicked samples, oldest first: ``{"key": record_key, "label"}``.
    _selected: list = []

    # Labels and units, as methods so a page whose series is a selection can
    # answer from its state; the default is the page's class setting.
    def _x_label(self) -> str:
        return self.X_LABEL

    def _y_label(self) -> str:
        return self.Y_LABEL

    def _y_name(self) -> str:
        return self.Y_NAME

    def _x_unit(self) -> str:
        return self.X_UNIT

    def panel_key(self) -> str:
        """Session-scoped buffer-store key; see the composition page's."""
        return f"{self.PANEL_PREFIX}-{self.router.session.client_token}"

    @rx.event
    def set_plate_id(self, value: str):
        self.plate_id = value

    def _clear_charts(self) -> None:
        self._loaded, self._plotted = [], []
        self._plotted_xs, self._plotted_ys = [], []
        self._selected = []
        self.selected_label = ""
        self.detail_rows = []
        self.map_spec, self.map_url, self.map_layout = {}, "", ""
        self.hist_spec, self.hist_url, self.hist_layout = {}, "", ""
        self.spec_spec, self.spec_url, self.spec_layout = {}, "", ""

    async def _load_and_draw(
        self, chosen, client, file_type: str = "", fetch=None
    ) -> None:
        """Load every spectrum of *chosen*, then draw. Call outside the lock.

        Args:
            file_type: Overrides the page's ``FILE_TYPE``, for a page whose
                file type is itself a selection.
            fetch: A page's own loader, ``async (chosen, progress) ->
                (failures, records)``, for spectra that are not one plottable
                file per record. The returned records are what gets plotted.
        """

        async def _progress(done, total):
            async with self:
                self.status = f"loading spectra: {done}/{total}"

        if fetch is not None:
            failures, chosen = await fetch(chosen, _progress)
        else:
            failures = await spectra.load_spectra(
                client,
                chosen,
                file_type=file_type or self.FILE_TYPE,
                x_key=self.X_KEY,
                y_key=self.Y_KEY,
                progress=_progress,
            )
        grid, _stack, loaded = spectra.stack_for(chosen)
        async with self:
            self._loaded = loaded
            if not loaded:
                self.error = "none of these spectra could be read"
                self.status = ""
                return
            self._fit_window(grid)
            failed = f", {failures} unreadable" if failures else ""
            self.status = f"{len(loaded)} spectra loaded{failed}"
            self.version += 1
            self._draw()

    def _fit_window(self, grid) -> None:
        """On a new x range, start both window edges at its midpoint."""
        low, high = float(grid.min()), float(grid.max())
        if (low, high) != (self.wl_min, self.wl_max):
            self.wl_min, self.wl_max = low, high
            self._set_window((low + high) / 2, (low + high) / 2)

    def _set_window(self, lo: float, hi: float) -> None:
        self.wl_lo = min(max(lo, self.wl_min), self.wl_max)
        self.wl_hi = min(max(hi, self.wl_min), self.wl_max)
        self.wl_lo_text = f"{self.wl_lo:.{self.DECIMALS}f}"
        self.wl_hi_text = f"{self.wl_hi:.{self.DECIMALS}f}"

    def _redraw(self) -> None:
        """Redraw after a window, size or selection change, keeping selection."""
        if not self._loaded:
            return
        self.version += 1
        self._draw()

    # -- window controls ----------------------------------------------------
    # The sliders are controlled: `on_change` only moves the thumb and the
    # readout, and the charts redraw on `on_value_commit` (release), so a drag
    # does not redraw three charts per step.
    @rx.event
    def drag_wl_lo(self, value: list[float]):
        self._set_window(float(value[0]), self.wl_hi)

    @rx.event
    def drag_wl_hi(self, value: list[float]):
        self._set_window(self.wl_lo, float(value[0]))

    @rx.event
    def commit_wl_lo(self, value: list[float]):
        self._set_window(float(value[0]), self.wl_hi)
        self._redraw()

    @rx.event
    def commit_wl_hi(self, value: list[float]):
        self._set_window(self.wl_lo, float(value[0]))
        self._redraw()

    @rx.event
    def set_wl_lo_text(self, value: str):
        self.wl_lo_text = value

    @rx.event
    def set_wl_hi_text(self, value: str):
        self.wl_hi_text = value

    @rx.event
    def apply_wl_text(self, _value: str = ""):
        """Apply both typed edges (on blur); an unparsable one reverts."""
        lo, hi = _as_number(self.wl_lo_text), _as_number(self.wl_hi_text)
        self._set_window(
            self.wl_lo if lo is None else lo, self.wl_hi if hi is None else hi
        )
        self._redraw()

    @rx.event
    def set_point_scale(self, value: list[float]):
        scale = float(value[0]) if value else 1.0
        self.point_scale = min(max(scale, 1.0), MAX_POINT_SCALE)
        self._redraw()

    @rx.event
    def set_overlay_spectra(self, value: bool):
        """Turning overlay off keeps only the most recent sample."""
        self.overlay_spectra = bool(value)
        if not self.overlay_spectra and len(self._selected) > 1:
            self._selected = self._selected[-1:]
            self._redraw()

    # -- drawing --------------------------------------------------------------
    def _draw(self) -> None:
        grid, stack, loaded = spectra.stack_for(self._loaded)
        means = spectra.window_means(grid, stack, self.wl_lo, self.wl_hi)
        self._draw_map(loaded, means)
        self._draw_histogram(means)
        self._draw_spectra(grid, stack, loaded)

    def _window_label(self) -> str:
        lo, hi = sorted((self.wl_lo, self.wl_hi))
        d = self.DECIMALS
        return f"mean {self._y_name()} {lo:.{d}f}-{hi:.{d}f} {self._x_unit()}".rstrip()

    def _draw_map(self, loaded, means) -> None:
        if not self._pm_rows:
            return
        by_sample = {row["sample_no"]: row for row in self._pm_rows}
        kept, xs, ys, values = [], [], [], []
        for record, mean in zip(loaded, means):
            row = by_sample.get(record.sample_no)
            if row is None or not np.isfinite(mean):
                continue
            kept.append(record)
            xs.append(row["x"])
            ys.append(row["y"])
            values.append(float(mean))
        self._plotted, self._plotted_xs, self._plotted_ys = kept, xs, ys
        where = {spectra.record_key(r): i for i, r in enumerate(kept)}
        rings = [
            (xs[where[s["key"]]], ys[where[s["key"]]], index)
            for index, s in enumerate(self._selected)
            if s["key"] in where
        ]
        payload = plots.scatter_map(
            xs,
            ys,
            values=values or None,
            x_label="x (mm)",
            y_label="y (mm)",
            value_label=self._window_label(),
            square=True,
            colormap=WINDOW_COLORMAP,
            colorbar=True,
            size=plots.DEFAULT_POINT_SIZE * self.point_scale,
            rings=rings,
            panel_id=f"{self.panel_key()}-map",
            version=self.version,
        )
        self.map_spec, self.map_url, self.map_layout = (
            payload.spec,
            payload.buffer_url,
            payload.layout,
        )

    def _draw_histogram(self, means) -> None:
        payload = plots.histogram(
            {self._window_label(): list(means)},
            bins=30,
            x_label=self._window_label(),
            panel_id=f"{self.panel_key()}-hist",
            version=self.version,
        )
        self.hist_spec, self.hist_url, self.hist_layout = (
            payload.spec,
            payload.buffer_url,
            payload.layout,
        )

    def _draw_spectra(self, grid, stack, loaded) -> None:
        rows = {spectra.record_key(r): i for i, r in enumerate(loaded)}
        series = [
            {"label": s["label"], "x": grid, "y": stack[rows[s["key"]]]}
            for s in self._selected
            if s["key"] in rows
        ]
        # Pad a zero-width window by half a grid step each side, so the band
        # shows the one point the window mean then reads.
        step = float(np.median(np.diff(grid))) if grid.size > 1 else 0.0
        lo, hi = sorted((self.wl_lo, self.wl_hi))
        if hi - lo < step:
            lo, hi = lo - step / 2, hi + step / 2
        payload = plots.spectra_over_background(
            (grid, stack.mean(axis=0)),
            series,
            window=(lo, hi),
            x_label=self._x_label(),
            y_label=self._y_label(),
            panel_id=f"{self.panel_key()}-spec",
            version=self.version,
        )
        self.spec_spec, self.spec_url, self.spec_layout = (
            payload.spec,
            payload.buffer_url,
            payload.layout,
        )

    # -- selection --------------------------------------------------------------
    @rx.event
    def on_map_select(self, payload: dict):
        """Select the sample nearest a click on the plate map."""
        x = _as_number((payload or {}).get("x"))
        y = _as_number((payload or {}).get("y"))
        if x is None or y is None:
            return
        record = nearest_record(self._plotted, self._plotted_xs, self._plotted_ys, x, y)
        if record is None:
            return
        hit = spectra.cached_spectrum(spectra.record_key(record))
        if hit is None:
            return
        grid, values = hit
        self.selected_label = (
            f"{record.global_label}   sample {record.sample_no}   "
            f"{record.run_use or grouping.NO_RUN_USE}"
        )
        self.detail_rows = detail_rows(
            record,
            grid,
            values,
            self.wl_lo,
            self.wl_hi,
            x_unit=self._x_unit(),
            stats_range=self.STATS_RANGE,
            decimals=self.DECIMALS,
        )
        entry = {
            "key": spectra.record_key(record),
            "label": f"sample {record.sample_no} {record.run_use}".strip(),
        }
        kept = (
            [s for s in self._selected if s["key"] != entry["key"]]
            if self.overlay_spectra
            else []
        )
        self._selected = kept + [entry]
        self._redraw()


# ---------------------------------------------------------------------------
# UI builders, parametrized by the page's state class
# ---------------------------------------------------------------------------
def _muted(text):
    return rx.text(text, size="1", class_name=reflex_muted_text_class())


def plate_row(S):
    """Plate id, Retrieve, status."""
    return rx.hstack(
        rx.input(
            placeholder="plate id",
            value=S.plate_id,
            on_change=S.set_plate_id,
            width="10em",
        ),
        rx.button("Retrieve", on_click=S.retrieve("")),
        rx.text(S.status, size="1"),
        spacing="3",
        align="center",
    )


def plot_controls(S):
    """Plot and the point-size slider, to follow a page's grouping selects."""
    return [
        rx.button("Plot", on_click=S.plot("")),
        _muted("point size"),
        rx.slider(
            default_value=[1.0],
            min=1.0,
            max=MAX_POINT_SCALE,
            step=0.5,
            on_value_commit=S.set_point_scale,
            width="10em",
        ),
    ]


def _slider_row(S, label, value, drag, commit, text, set_text, unit, step):
    """One window edge: label, slider, and an editable numeric readout."""
    return rx.hstack(
        rx.text(label, size="1", class_name=reflex_muted_text_class(), width="6em"),
        rx.slider(
            value=[value],
            min=S.wl_min,
            max=S.wl_max,
            step=step,
            on_change=drag,
            on_value_commit=commit,
            width="24em",
        ),
        rx.input(
            value=text,
            on_change=set_text,
            on_blur=S.apply_wl_text,
            width="6em",
        ),
        _muted(unit),
        spacing="3",
        align="center",
    )


def window_rows(S, unit: str):
    """The two window-edge rows, stepping by the page's ``SLIDER_STEP``."""
    return [
        _slider_row(
            S,
            "window from",
            S.wl_lo,
            S.drag_wl_lo,
            S.commit_wl_lo,
            S.wl_lo_text,
            S.set_wl_lo_text,
            unit,
            S.SLIDER_STEP,
        ),
        _slider_row(
            S,
            "window to",
            S.wl_hi,
            S.drag_wl_hi,
            S.commit_wl_hi,
            S.wl_hi_text,
            S.set_wl_hi_text,
            unit,
            S.SLIDER_STEP,
        ),
    ]


def charts(S):
    """Error line, the chart row (map, histogram, info), and the spectrum."""
    width = plots.square_width(CHART_HEIGHT)
    map_panel = rx.cond(
        S.platemap_note != "",
        _muted(S.platemap_note),
        plots.chart(
            S.map_spec,
            S.map_url,
            S.map_layout,
            height=CHART_HEIGHT,
            width=width,
            on_select=S.on_map_select,
        ),
    )
    histogram = plots.chart(
        S.hist_spec, S.hist_url, S.hist_layout, height=CHART_HEIGHT, width=width
    )
    info = rx.vstack(
        rx.text(S.selected_label, size="2"),
        rx.table.root(
            rx.table.body(
                rx.foreach(
                    S.detail_rows,
                    lambda row: rx.table.row(
                        rx.foreach(row, lambda cell: rx.table.cell(cell))
                    ),
                )
            ),
            class_name=reflex_table_class("action"),
            width="100%",
        ),
        flex="1",
        min_width="22em",
        max_height=f"{CHART_HEIGHT + 48}px",
        overflow_y="auto",
        spacing="2",
    )
    spectrum = rx.vstack(
        rx.checkbox(
            "Overlay spectra",
            checked=S.overlay_spectra,
            on_change=S.set_overlay_spectra,
        ),
        plots.chart(S.spec_spec, S.spec_url, S.spec_layout, height=SPECTRUM_HEIGHT),
        width="100%",
        spacing="2",
    )
    return [
        rx.cond(S.error != "", rx.text(S.error, class_name="text-red-600", size="1")),
        rx.hstack(
            map_panel,
            histogram,
            info,
            width="100%",
            spacing="4",
            align="start",
            flex_wrap="wrap",
        ),
        spectrum,
    ]
