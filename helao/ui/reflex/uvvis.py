# helao/ui/reflex/uvvis.py
"""The `/uvvis` page: R_UVVIS reflectance spectra across one plate.

Built on the composition page's pattern. An operator enters a plate id and
Retrieve lists the plate's R_UVVIS spectra (see ``helao.ui.shared.uvvis`` for
how they are found); a run_id and a run_use pick which ones, and Plot loads
them all. The page then shows

* a plate map coloured by each sample's mean intensity inside a wavelength
  window set by two sliders,
* a histogram of those window means where the composition page has its
  ternary, and
* the spectrum chart: the selection's average spectrum in grey with the
  window shaded over it, and clicked samples' spectra on top.

The composition page's rules hold here too: charts are bound once in
:func:`build_page`, nothing polls, and ``rx.foreach`` vars are annotated.
"""

from __future__ import annotations

import numpy as np
import reflex as rx

from helao.helpers import helao_logging as logging
from helao.ui.reflex import plots
from helao.ui.reflex.composition import (
    CHART_HEIGHT,
    MAX_POINT_SCALE,
    SPECTRUM_HEIGHT,
    nearest_record,
    parse_plate_id,
    platemap_for,
)
from helao.ui.shared import uvvis
from helao.ui.shared.composition import api, grouping
from helao.ui.shared.palette import (
    WINDOW_COLORMAP,
    reflex_muted_text_class,
    reflex_table_class,
)
from helao.ui.shared.platemap import _as_number

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: The run_use a run's selection defaults to when it has one.
DEFAULT_RUN_USE = "data"


def _fmt(value) -> str:
    return f"{value:.6g}"


def run_use_options(records, run_id: str) -> list:
    """``All`` plus every run_use in *run_id*, sorted."""
    uses = {r.run_use or grouping.NO_RUN_USE for r in records if r.run_id == run_id}
    return [grouping.ALL] + sorted(uses)


def select_records(records, run_id: str, run_use: str) -> list:
    """The records of one run, narrowed to one run_use unless ``All``."""
    return [
        r
        for r in records
        if r.run_id == run_id
        and (run_use == grouping.ALL or (r.run_use or grouping.NO_RUN_USE) == run_use)
    ]


def detail_rows(record, wl, intensity, lo: float, hi: float) -> list:
    """The selected sample's table: its window mean and 350-1000 nm stats."""
    lo, hi = min(lo, hi), max(lo, hi)
    rows = [
        ["quantity", "value"],
        ["run_use", record.run_use or grouping.NO_RUN_USE],
        [
            f"window mean ({lo:.1f}-{hi:.1f} nm)",
            _fmt(uvvis.window_mean(wl, intensity, lo, hi)),
        ],
    ]
    r0, r1 = uvvis.STATS_RANGE
    stats = uvvis.range_stats(wl, intensity, r0, r1)
    for name in ("min", "mean", "max", "stdev"):
        value = stats.get(name)
        rows.append(
            [f"{name} ({r0:g}-{r1:g} nm)", "-" if value is None else _fmt(value)]
        )
    return rows


class UvvisState(rx.State):
    """Everything the UV-Vis page holds, except the spectra themselves."""

    plate_id: str = ""
    status: str = ""
    error: str = ""
    platemap_note: str = ""

    run_choice: str = ""
    run_use_choice: str = grouping.ALL
    run_options: list[str] = []
    run_use_options: list[str] = []

    #: The loaded grid's wavelength range, and the window on it.
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

    #: Backend only. Spectra are in `uvvis`'s module cache, keyed by the
    #: records' process uuids.
    _records: list = []
    _runs: dict = {}
    _pm_rows: list = []
    #: The records Plot loaded, and those of them on the plate map.
    _loaded: list = []
    _plotted: list = []
    _plotted_xs: list = []
    _plotted_ys: list = []
    #: Clicked samples, oldest first: ``{"key": process_uuid, "label"}``.
    _selected: list = []

    def panel_key(self) -> str:
        """Session-scoped buffer-store key; see the composition page's."""
        return f"uvvis-{self.router.session.client_token}"

    @rx.event
    def set_plate_id(self, value: str):
        self.plate_id = value

    @rx.event
    def set_run(self, value: str):
        self.run_choice = value
        self._refresh_run_uses()

    @rx.event
    def set_run_use(self, value: str):
        self.run_use_choice = value

    def _refresh_run_uses(self) -> None:
        options = run_use_options(self._records, self._runs.get(self.run_choice, ""))
        self.run_use_options = options
        if self.run_use_choice not in options:
            self.run_use_choice = (
                DEFAULT_RUN_USE if DEFAULT_RUN_USE in options else grouping.ALL
            )

    def _clear_charts(self) -> None:
        self._loaded, self._plotted = [], []
        self._plotted_xs, self._plotted_ys = [], []
        self._selected = []
        self.selected_label = ""
        self.detail_rows = []
        self.map_spec, self.map_url, self.map_layout = {}, "", ""
        self.hist_spec, self.hist_url, self.hist_layout = {}, "", ""
        self.spec_spec, self.spec_url, self.spec_layout = {}, "", ""

    @rx.event(background=True)
    async def retrieve(self, _tick: str = ""):
        """List every R_UVVIS spectrum on the entered plate; loads no spectra."""
        async with self:
            plate_id = parse_plate_id(self.plate_id)
            self.error, self.status = "", ""
            self._clear_charts()
        if plate_id is None:
            async with self:
                self.error = f"'{self.plate_id}' is not a plate id"
            return
        async with self:
            self.status = f"finding plate {plate_id}'s R_UVVIS runs..."
        try:
            records = await uvvis.records_for_plate(api.get_client(), plate_id)
        except Exception as exc:
            LOGGER.warning(f"uvvis could not list plate {plate_id}: {exc}")
            async with self:
                self.error = f"plate {plate_id} could not be listed: {exc}"
                self.status = ""
            return
        rows, note = platemap_for(plate_id)
        async with self:
            self._records = records
            self._pm_rows = rows
            self.platemap_note = note
            run_ids = sorted({r.run_id for r in records if r.run_id}, reverse=True)
            self._runs = {uvvis.run_label(run_id): run_id for run_id in run_ids}
            self.run_options = list(self._runs)
            self.run_choice = self.run_options[0] if self.run_options else ""
            self._refresh_run_uses()
            if records:
                self.status = (
                    f"plate {plate_id}: {len(records)} R_UVVIS spectra in "
                    f"{len(run_ids)} runs"
                )
            else:
                # Found through sequence_params.plate_id, which older
                # sequences only gain as the API backfill reaches them.
                self.status = (
                    f"plate {plate_id}: no R_UVVIS sequences found (older "
                    f"sequences appear once the API backfill reaches them)"
                )

    @rx.event(background=True)
    async def plot(self, _tick: str = ""):
        """Load every spectrum of the chosen run and run_use, then draw."""
        async with self:
            self.error = ""
            self._clear_charts()
            chosen = select_records(
                self._records, self._runs.get(self.run_choice, ""), self.run_use_choice
            )
            if not chosen:
                self.status = "nothing matches this run and run_use"
                return
            self.status = f"loading {len(chosen)} spectra..."

        async def _progress(done, total):
            async with self:
                self.status = f"loading spectra: {done}/{total}"

        failures = await uvvis.load_spectra(api.get_client(), chosen, _progress)
        wl, _stack, loaded = uvvis.stack_for(chosen)
        async with self:
            self._loaded = loaded
            if not loaded:
                self.error = "none of this run's spectra could be read"
                self.status = ""
                return
            low, high = float(wl.min()), float(wl.max())
            if (low, high) != (self.wl_min, self.wl_max):
                # A new grid: both window edges start at its midpoint.
                self.wl_min, self.wl_max = low, high
                self._set_window((low + high) / 2, (low + high) / 2)
            failed = f", {failures} unreadable" if failures else ""
            self.status = f"{len(loaded)} spectra loaded{failed}"
            self.version += 1
            self._draw()

    def _set_window(self, lo: float, hi: float) -> None:
        self.wl_lo = min(max(lo, self.wl_min), self.wl_max)
        self.wl_hi = min(max(hi, self.wl_min), self.wl_max)
        self.wl_lo_text = f"{self.wl_lo:.1f}"
        self.wl_hi_text = f"{self.wl_hi:.1f}"

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
        wl, stack, loaded = uvvis.stack_for(self._loaded)
        means = uvvis.window_means(wl, stack, self.wl_lo, self.wl_hi)
        self._draw_map(loaded, means)
        self._draw_histogram(means)
        self._draw_spectra(wl, stack, loaded)

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
        where = {r.process_uuid: i for i, r in enumerate(kept)}
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

    def _window_label(self) -> str:
        lo, hi = sorted((self.wl_lo, self.wl_hi))
        return f"mean intensity {lo:.1f}-{hi:.1f} nm"

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

    def _draw_spectra(self, wl, stack, loaded) -> None:
        rows = {r.process_uuid: i for i, r in enumerate(loaded)}
        series = [
            {"label": s["label"], "x": wl, "y": stack[rows[s["key"]]]}
            for s in self._selected
            if s["key"] in rows
        ]
        # Pad a zero-width window by half a grid step each side, so the band
        # shows the one wavelength the window mean then reads.
        step = float(np.median(np.diff(wl))) if wl.size > 1 else 0.0
        lo, hi = sorted((self.wl_lo, self.wl_hi))
        if hi - lo < step:
            lo, hi = lo - step / 2, hi + step / 2
        payload = plots.spectra_over_background(
            (wl, stack.mean(axis=0)),
            series,
            window=(lo, hi),
            x_label="wavelength (nm)",
            y_label="intensity",
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
        hit = uvvis.cached_spectrum(record.process_uuid)
        if hit is None:
            return
        wl, intensity = hit
        self.selected_label = (
            f"{record.global_label}   sample {record.sample_no}   "
            f"{record.run_use or grouping.NO_RUN_USE}"
        )
        self.detail_rows = detail_rows(record, wl, intensity, self.wl_lo, self.wl_hi)
        entry = {
            "key": record.process_uuid,
            "label": f"sample {record.sample_no} {record.run_use}".strip(),
        }
        kept = (
            [s for s in self._selected if s["key"] != entry["key"]]
            if self.overlay_spectra
            else []
        )
        self._selected = kept + [entry]
        self._redraw()


def _slider_row(label, value, drag, commit, text, set_text):
    """One window edge: label, slider, and an editable numeric readout."""
    return rx.hstack(
        rx.text(label, size="1", class_name=reflex_muted_text_class(), width="6em"),
        rx.slider(
            value=[value],
            min=UvvisState.wl_min,
            max=UvvisState.wl_max,
            step=0.5,
            on_change=drag,
            on_value_commit=commit,
            width="24em",
        ),
        rx.input(
            value=text,
            on_change=set_text,
            on_blur=UvvisState.apply_wl_text,
            width="6em",
        ),
        rx.text("nm", size="1", class_name=reflex_muted_text_class()),
        spacing="3",
        align="center",
    )


def _controls():
    """Plate id, run and run_use dropdowns, Plot, and the chart controls."""
    return rx.vstack(
        rx.hstack(
            rx.input(
                placeholder="plate id",
                value=UvvisState.plate_id,
                on_change=UvvisState.set_plate_id,
                width="10em",
            ),
            rx.button("Retrieve", on_click=UvvisState.retrieve("")),
            rx.text(UvvisState.status, size="1"),
            spacing="3",
            align="center",
        ),
        rx.hstack(
            rx.text("run_id", size="1", class_name=reflex_muted_text_class()),
            rx.select(
                UvvisState.run_options,
                value=UvvisState.run_choice,
                on_change=UvvisState.set_run,
                width="32em",
            ),
            rx.text("run_use", size="1", class_name=reflex_muted_text_class()),
            rx.select(
                UvvisState.run_use_options,
                value=UvvisState.run_use_choice,
                on_change=UvvisState.set_run_use,
                width="12em",
            ),
            rx.button("Plot", on_click=UvvisState.plot("")),
            rx.text("point size", size="1", class_name=reflex_muted_text_class()),
            rx.slider(
                default_value=[1.0],
                min=1.0,
                max=MAX_POINT_SCALE,
                step=0.5,
                on_value_commit=UvvisState.set_point_scale,
                width="10em",
            ),
            spacing="3",
            align="center",
        ),
        _slider_row(
            "window from",
            UvvisState.wl_lo,
            UvvisState.drag_wl_lo,
            UvvisState.commit_wl_lo,
            UvvisState.wl_lo_text,
            UvvisState.set_wl_lo_text,
        ),
        _slider_row(
            "window to",
            UvvisState.wl_hi,
            UvvisState.drag_wl_hi,
            UvvisState.commit_wl_hi,
            UvvisState.wl_hi_text,
            UvvisState.set_wl_hi_text,
        ),
        width="100%",
        spacing="2",
    )


def _map_panel():
    return rx.cond(
        UvvisState.platemap_note != "",
        rx.text(
            UvvisState.platemap_note, size="1", class_name=reflex_muted_text_class()
        ),
        plots.chart(
            UvvisState.map_spec,
            UvvisState.map_url,
            UvvisState.map_layout,
            height=CHART_HEIGHT,
            width=plots.square_width(CHART_HEIGHT),
            on_select=UvvisState.on_map_select,
        ),
    )


def _histogram_panel():
    return plots.chart(
        UvvisState.hist_spec,
        UvvisState.hist_url,
        UvvisState.hist_layout,
        height=CHART_HEIGHT,
        width=plots.square_width(CHART_HEIGHT),
    )


def _info_panel():
    """Same shape as the composition page's: capped, scrolling."""
    return rx.vstack(
        rx.text(UvvisState.selected_label, size="2"),
        rx.table.root(
            rx.table.body(
                rx.foreach(
                    UvvisState.detail_rows,
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


def _spectrum_panel():
    return rx.vstack(
        rx.checkbox(
            "Overlay spectra",
            checked=UvvisState.overlay_spectra,
            on_change=UvvisState.set_overlay_spectra,
        ),
        plots.chart(
            UvvisState.spec_spec,
            UvvisState.spec_url,
            UvvisState.spec_layout,
            height=SPECTRUM_HEIGHT,
        ),
        width="100%",
        spacing="2",
    )


def build_page():
    """Render the UV-Vis page.

    Returns:
        rx.Component: The page body.
    """
    return rx.vstack(
        _controls(),
        rx.cond(
            UvvisState.error != "",
            rx.text(UvvisState.error, class_name="text-red-600", size="1"),
        ),
        rx.hstack(
            _map_panel(),
            _histogram_panel(),
            _info_panel(),
            width="100%",
            spacing="4",
            align="start",
            flex_wrap="wrap",
        ),
        _spectrum_panel(),
        width="100%",
        spacing="4",
        padding_x="1em",
    )
