# helao/ui/reflex/composition.py
"""The `/composition` page: XRF analyses across one plate.

An operator enters a plate id; the page loads every XRF process the metadata
API has for that plate, groups them by ``run_use`` and by sequence, and plots a
chosen transition and unit as a platemap scatter and a ternary diagram.
Clicking a point shows that sample's full analysis output and its spectrum.

Three rules this stack has already paid for, restated because each fails at a
different moment:

* ``plots.chart`` is bound **once**, in :func:`build_page`. The facade functions
  are called from event handlers and their payloads assigned into state. A
  facade call in the body paints once and never updates.
* There is **no polling loop**. ``on_unmount`` does not fire on tab close, so a
  server-side ``while True`` outlives the browser. This page has no cadence:
  every render follows a button press or a click.
* Every ``rx.foreach`` var carries an element annotation. A bare ``list`` fails
  the *frontend build* with ``ForeachVarError``, not at import.
"""

from __future__ import annotations

import asyncio
import math
import threading
from dataclasses import dataclass
from typing import Optional

import reflex as rx

from helao.helpers import helao_logging as logging
from helao.ui.reflex import plots
from helao.ui.shared import platemap
from helao.ui.shared.composition import api, grouping, interp, model
from helao.ui.shared.composition import ternary as _ternary
from helao.ui.shared.palette import reflex_muted_text_class, reflex_table_class
from helao.ui.shared.platemap import _as_number

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Concurrent quantification fetches. Matches the bound the existing XRFS
#: lookups use against this API.
MAX_CONCURRENT_FETCHES = 30

#: How a missing value reads in the details table.
MISSING = "-"

#: Height of the plate map and ternary diagram, both square. 520 is about the
#: least that keeps them out of xy's compact layout (see `plots.square_width`).
CHART_HEIGHT = 520

_SETTINGS: dict = {}
_SETTINGS_LOCK = threading.Lock()


def configure(world_cfg: dict, server_key: str) -> None:
    """Record the config this page resolves its plate API from.

    Called from ``build_app``, as ``configure_operator`` and
    ``configure_control`` already are.
    """
    with _SETTINGS_LOCK:
        _SETTINGS.update({"world_cfg": world_cfg or {}, "server_key": server_key})


def world_config() -> dict:
    """The config recorded by :func:`configure`."""
    with _SETTINGS_LOCK:
        return _SETTINGS.get("world_cfg") or {}


def parse_plate_id(raw: str) -> Optional[int]:
    """The entered plate id, or ``None`` when it is not one."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Loaded:
    """What one Retrieve produced."""

    records: list
    failures: int


async def load_records(plate_id: int) -> Loaded:
    """Every XRF record for *plate_id*, with its analysis values folded in.

    The quantification fetches fan out under a semaphore and collect
    exceptions: one unreadable HLO out of several hundred must be counted and
    reported, not allowed to abort the load.
    """
    client = api.get_client()
    items = await api.search_processes(client, plate_id)
    uuids = sorted({str(item.get("sequence_uuid") or "") for item in items})
    sequences = await api.fetch_sequences(client, uuids)
    records = [
        record
        for record in (model.record_from_process(item, sequences) for item in items)
        if record is not None
    ]
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    async def _one(record):
        async with semaphore:
            return await api.fetch_quant(
                client, record.quant_action_uuid, record.quant_file_name
            )

    payloads = await asyncio.gather(
        *(_one(record) for record in records), return_exceptions=True
    )
    loaded = []
    failures = 0
    for record, payload in zip(records, payloads):
        if isinstance(payload, BaseException):
            failures += 1
            LOGGER.warning(
                f"composition could not read {record.quant_file_name} "
                f"for action {record.quant_action_uuid}: {payload}"
            )
            continue
        loaded.append(model.with_values(record, payload))
    return Loaded(records=loaded, failures=failures)


def platemap_for(plate_id: int) -> tuple:
    """``(rows, note)`` for *plate_id*, from the configured plate API.

    The note distinguishes three causes, because the operator's next move
    differs in each: no plate API is declared in this config, credentials are
    unavailable, or this particular plate would not load.
    """
    plate_api = platemap.plate_api_for_config(world_config())
    if plate_api is None:
        return [], "no plate API is configured, so there is no platemap to plot against"
    if not plate_api.has_access:
        return (
            [],
            "the platemap needs credentials; set HELAO_CREDENTIALS to a readable "
            "environment file",
        )
    try:
        pmdata = plate_api.get_platemap_plateid(plate_id)
    except Exception as exc:
        LOGGER.warning(f"composition could not load plate {plate_id}: {exc}")
        return [], f"plate {plate_id}'s platemap could not be read: {exc}"
    rows = platemap.platemap_rows(pmdata)
    if not rows:
        return [], f"plate {plate_id} has no platemap rows with usable coordinates"
    return rows, ""


def series_for(records, transition: str, unit: str) -> list:
    """One value per record, ``None`` where the record has no such measurement.

    The slot is kept rather than dropped because the caller indexes this
    against a parallel array of records.
    """
    out = []
    for record in records or []:
        out.append((record.values.get(transition) or {}).get(unit))
    return out


def map_arrays(records, pm_rows, transition: str, unit: str) -> tuple:
    """``(xs, ys, values, kept_records)`` for the plate-map scatter.

    Joined on the platemap's own ``sample_no``. A record with no platemap row,
    or whose selected value is ``None``, is dropped from all four outputs
    together -- ``None`` is an uncalibrated transition, and plotting it as
    ``0.0`` would read as a measurement.
    """
    by_sample = {row["sample_no"]: row for row in pm_rows or []}
    xs, ys, values, kept = [], [], [], []
    for record in records or []:
        row = by_sample.get(record.sample_no)
        if row is None:
            continue
        value = (record.values.get(transition) or {}).get(unit)
        if value is None:
            continue
        xs.append(row["x"])
        ys.append(row["y"])
        values.append(value)
        kept.append(record)
    return xs, ys, values, kept


def detail_rows(record) -> list:
    """The selected sample's whole analysis output, as table rows.

    First row is the header. Every transition is listed against every unit any
    transition carries, so a missing measurement shows as a gap rather than
    shifting the columns.
    """
    if record is None:
        return []
    units = sorted({unit for per_unit in record.values.values() for unit in per_unit})
    rows = [["transition"] + units]
    for transition in sorted(record.values):
        per_unit = record.values[transition]
        cells = []
        for unit in units:
            value = per_unit.get(unit)
            cells.append(MISSING if value is None else f"{value:g}")
        rows.append([transition] + cells)
    return rows


def ternary_fractions(record, vertices, unit: str) -> str:
    """The sample's normalized ternary fractions, as one line of text.

    The fractions are what the ternary diagram plots, so the click panel
    stands in for a tooltip xy cannot show. Empty when a vertex is unset or
    the sample lacks a finite, non-negative value for one, since such a point
    is not on the diagram.
    """
    if record is None or not all(vertices):
        return ""
    values = [(record.values.get(vertex) or {}).get(unit) for vertex in vertices]
    if any(
        not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values
    ):
        return ""
    total = sum(values)
    if total <= 0:
        return ""
    parts = "   ".join(
        f"{vertex} {value / total:.3f}" for vertex, value in zip(vertices, values)
    )
    return f"ternary fractions ({unit}):   {parts}"


def _kept_or_first(choice: str, options: list) -> str:
    """*choice* if *options* still offers it, else the first option."""
    if choice in options:
        return choice
    return options[0] if options else ""


def _vertices(current, options: list) -> tuple:
    """Three ternary vertices: the current ones still offered, gaps refilled.

    Refilled from *options* in order, skipping names already in use, so the
    three stay distinct whenever there are three to choose from.
    """
    kept = [name if name in options else "" for name in current]
    spare = [name for name in options if name not in kept]
    return tuple(name or (spare.pop(0) if spare else "") for name in kept)


def nearest_record(records, xs, ys, x: float, y: float):
    """The record nearest ``(x, y)`` in the plotted plane, or ``None``.

    The chart reports a **coordinate**, never a row id: ``xy_component`` wires
    only ``on_select``, whose payload carries ``x`` and ``y``. Matching happens
    in the plane the click is in, which on the ternary diagram is the
    transformed plane -- searching the barycentric triples would find a
    different point wherever the triangle is anisotropic on screen.
    """
    if not records or not xs:
        return None
    index = min(range(len(xs)), key=lambda i: (xs[i] - x) ** 2 + (ys[i] - y) ** 2)
    return records[index] if index < len(records) else None


class CompositionState(rx.State):
    """Everything the composition page holds."""

    plate_id: str = ""
    status: str = ""
    error: str = ""
    platemap_note: str = ""

    run_use_choice: str = grouping.ALL
    sequence_choice: str = grouping.ALL
    transition_choice: str = ""
    unit_choice: str = ""
    vertex_a: str = ""
    vertex_b: str = ""
    vertex_c: str = ""
    interpolate: bool = False

    run_use_options: list[str] = []
    sequence_options: list[str] = []
    transition_options: list[str] = []
    unit_options: list[str] = []

    selected_label: str = ""
    ternary_label: str = ""
    detail_rows: list[list[str]] = []

    map_spec: dict = {}
    map_url: str = ""
    map_layout: str = ""
    tern_spec: dict = {}
    tern_url: str = ""
    tern_layout: str = ""
    spec_spec: dict = {}
    spec_url: str = ""
    spec_layout: str = ""

    version: int = 0

    #: Backend vars: the browser needs the rendered points, not the records.
    _records: list = []
    _pm_rows: list = []
    _plotted: list = []
    _plotted_xs: list = []
    _plotted_ys: list = []
    #: Same as the three above, but for the ternary diagram -- kept separate
    #: because `plot()` draws both charts, and one selection array would be
    #: clobbered by the other's coordinates.
    _tern_plotted: list = []
    _tern_plotted_xs: list = []
    _tern_plotted_ys: list = []

    def panel_key(self) -> str:
        """Session-scoped buffer-store key.

        The store holds one frame per key while ``version`` is per-session
        state, so a shared key would 404 two tabs into frozen charts.
        """
        return f"composition-{self.router.session.client_token}"

    @rx.event
    def set_plate_id(self, value: str):
        self.plate_id = value

    @rx.event
    def set_run_use(self, value: str):
        self.run_use_choice = value
        self._refresh_options()

    @rx.event
    def set_sequence(self, value: str):
        self.sequence_choice = value
        self._refresh_options()

    def _refresh_options(self) -> None:
        """Narrow each dropdown to what the selections above it leave.

        run_use scopes the sequences; run_use and sequence together scope the
        transitions and units. A choice the new scope no longer offers falls
        back to the first option (``All`` for sequence) rather than lingering
        as a selection that matches nothing.
        """
        by_run_use = grouping.filter_records(
            self._records, run_use=self.run_use_choice, sequence=grouping.ALL
        )
        self.sequence_options = grouping.sequence_options(by_run_use)
        if self.sequence_choice not in self.sequence_options:
            self.sequence_choice = grouping.ALL
        scoped = grouping.filter_records(
            by_run_use, run_use=grouping.ALL, sequence=self.sequence_choice
        )
        self.transition_options = model.transition_names(scoped)
        self.unit_options = model.unit_names(scoped)
        self.transition_choice = _kept_or_first(
            self.transition_choice, self.transition_options
        )
        self.unit_choice = _kept_or_first(self.unit_choice, self.unit_options)
        vertices = _vertices(
            (self.vertex_a, self.vertex_b, self.vertex_c), self.transition_options
        )
        self.vertex_a, self.vertex_b, self.vertex_c = vertices

    @rx.event
    def set_transition(self, value: str):
        self.transition_choice = value

    @rx.event
    def set_unit(self, value: str):
        self.unit_choice = value

    @rx.event
    def set_vertex_a(self, value: str):
        self.vertex_a = value

    @rx.event
    def set_vertex_b(self, value: str):
        self.vertex_b = value

    @rx.event
    def set_vertex_c(self, value: str):
        self.vertex_c = value

    @rx.event
    def set_interpolate(self, value: bool):
        """A checkbox value is a bool, never a string.

        ``bool("False")`` is ``True``, so routing this through the text
        coercion would invert every unchecked box.
        """
        self.interpolate = bool(value)

    @rx.event(background=True)
    async def retrieve(self, _tick: str = ""):
        """Load every XRF record for the entered plate id.

        The default argument is not decoration: a handler bound to a button
        receives a ``PointerEventInfo``, and one bound to anything that supplies
        a value receives that value. Binding a no-argument handler to a button
        raises ``EventHandlerArgTypeMismatchError`` **at render**.
        """
        async with self:
            plate_id = parse_plate_id(self.plate_id)
            self.error = ""
            self.status = ""
            # A new plate must not inherit the previous one's selection or
            # charts: without this, a plate with no platemap left the prior
            # plate's map on screen next to the new plate's ternary, and a
            # click on it resolved to the prior plate's record.
            self._plotted, self._plotted_xs, self._plotted_ys = [], [], []
            self._tern_plotted = []
            self._tern_plotted_xs, self._tern_plotted_ys = [], []
            self.map_spec, self.map_url, self.map_layout = {}, "", ""
            self.tern_spec, self.tern_url, self.tern_layout = {}, "", ""
            self.selected_label = ""
            self.ternary_label = ""
            self.detail_rows = []
            self.spec_spec, self.spec_url, self.spec_layout = {}, "", ""
        if plate_id is None:
            async with self:
                self.error = f"'{self.plate_id}' is not a plate id"
            return
        async with self:
            self.status = f"loading plate {plate_id}..."
        try:
            loaded = await load_records(plate_id)
        except Exception as exc:
            LOGGER.warning(f"composition could not load plate {plate_id}: {exc}")
            async with self:
                self.error = f"plate {plate_id} could not be loaded: {exc}"
                self.status = ""
            return
        rows, note = platemap_for(plate_id)
        async with self:
            self._records = loaded.records
            self._pm_rows = rows
            self.platemap_note = note
            self.run_use_options = grouping.run_use_options(loaded.records)
            self.run_use_choice = grouping.ALL
            self.sequence_choice = grouping.ALL
            self.transition_choice = self.unit_choice = ""
            self.vertex_a = self.vertex_b = self.vertex_c = ""
            self._refresh_options()
            failed = f", {loaded.failures} unreadable" if loaded.failures else ""
            self.status = (
                f"plate {plate_id}: {len(loaded.records)} XRF processes{failed}"
            )

    @rx.event
    def plot(self, _tick: str = ""):
        """Render the plate map and the ternary diagram from the selections."""
        self.error = ""
        # Cleared unconditionally, before either early return below: a plate
        # with no platemap (``_draw_map`` returns early) or a grouping with no
        # matching records must not leave the previous plot's chart and
        # selectable points on screen -- a click on a stale map used to
        # resolve to a stale record under the new plate's own header.
        self._plotted, self._plotted_xs, self._plotted_ys = [], [], []
        self._tern_plotted = []
        self._tern_plotted_xs, self._tern_plotted_ys = [], []
        self.map_spec, self.map_url, self.map_layout = {}, "", ""
        self.tern_spec, self.tern_url, self.tern_layout = {}, "", ""
        # A view that no longer contains the selected sample must not keep
        # showing its details panel and spectrum: without this, changing the
        # grouping to one that excludes the selected sample left its details
        # table, label and spectrum chart on screen next to the new (empty or
        # different) plot.
        self.selected_label = ""
        self.ternary_label = ""
        self.detail_rows = []
        self.spec_spec, self.spec_url, self.spec_layout = {}, "", ""
        records = grouping.filter_records(
            self._records,
            run_use=self.run_use_choice,
            sequence=self.sequence_choice,
        )
        if not records:
            self.status = "nothing matches this grouping"
            return
        self.version += 1
        self._draw_map(records)
        self._draw_ternary(records)

    def _draw_map(self, records) -> None:
        """The plate-map scatter, measured or interpolated."""
        if not self._pm_rows:
            return
        xs, ys, values, kept = map_arrays(
            records, self._pm_rows, self.transition_choice, self.unit_choice
        )
        self._plotted = kept
        self._plotted_xs = list(xs)
        self._plotted_ys = list(ys)
        plot_xs, plot_ys, plot_values = xs, ys, values
        if self.interpolate:
            target_xs = [row["x"] for row in self._pm_rows]
            target_ys = [row["y"] for row in self._pm_rows]
            surface = interp.rbf_surface(xs, ys, values, target_xs, target_ys)
            if surface.size == 0:
                self.status = (
                    f"fewer than {interp.MIN_POINTS} measured points; "
                    f"showing the measured samples instead"
                )
            else:
                plot_xs, plot_ys, plot_values = target_xs, target_ys, surface.tolist()
        payload = plots.scatter_map(
            plot_xs,
            plot_ys,
            values=plot_values or None,
            x_label="x (mm)",
            y_label="y (mm)",
            value_label=f"{self.transition_choice} {self.unit_choice}",
            square=True,
            panel_id=f"{self.panel_key()}-map",
            version=self.version,
        )
        self.map_spec = payload.spec
        self.map_url = payload.buffer_url
        self.map_layout = payload.layout

    def _draw_ternary(self, records) -> None:
        """The ternary diagram over the three chosen vertices."""
        vertices = (self.vertex_a, self.vertex_b, self.vertex_c)
        if not all(vertices):
            self.error = "pick three transitions for the ternary vertices"
            return
        unit = self.unit_choice
        components = [
            [
                value if value is not None else float("nan")
                for value in series_for(records, vertex, unit)
            ]
            for vertex in vertices
        ]
        # Same projection `plots.ternary` computes internally -- recomputed
        # here (not read back from the payload, which carries none of this)
        # so a click can be matched against the plane it lands in. `keep` is
        # a mask over `records`, so the two stay index-aligned.
        xs, ys, keep = _ternary.barycentric_to_cartesian(*components)
        self._tern_plotted = [record for record, kept in zip(records, keep) if kept]
        self._tern_plotted_xs = list(xs)
        self._tern_plotted_ys = list(ys)
        payload = plots.ternary(
            components[0],
            components[1],
            components[2],
            labels=vertices,
            panel_id=f"{self.panel_key()}-tern",
            version=self.version,
        )
        self.tern_spec = payload.spec
        self.tern_url = payload.buffer_url
        self.tern_layout = payload.layout

    @rx.event(background=True)
    async def on_map_select(self, payload: dict):
        """Snap to the measured sample nearest a click on the plate map.

        On the interpolated surface a click may land where nothing was
        measured; it resolves to the nearest measured sample and the details
        panel names which, so an interpolated value is never shown as a
        measurement.
        """
        x = _as_number((payload or {}).get("x"))
        y = _as_number((payload or {}).get("y"))
        if x is None or y is None:
            return
        async with self:
            record = nearest_record(
                self._plotted, self._plotted_xs, self._plotted_ys, x, y
            )
        await self._select(record)

    @rx.event(background=True)
    async def on_tern_select(self, payload: dict):
        """Snap to the sample nearest a click on the ternary diagram.

        Matched against `_tern_plotted_xs`/`_ys`, the transformed plane
        `_draw_ternary` stored -- the plane the click reports, and the plane
        that plane's own triangle may be anisotropic in.
        """
        x = _as_number((payload or {}).get("x"))
        y = _as_number((payload or {}).get("y"))
        if x is None or y is None:
            return
        async with self:
            record = nearest_record(
                self._tern_plotted, self._tern_plotted_xs, self._tern_plotted_ys, x, y
            )
        await self._select(record)

    async def _select(self, record) -> None:
        """Fill the details panel and load the spectrum for *record*."""
        if record is None:
            return
        async with self:
            self.error = ""
            self.selected_label = (
                f"{record.global_label}   sample {record.sample_no}   "
                f"{record.run_use or '(no run_use)'}"
            )
            self.detail_rows = detail_rows(record)
            self.ternary_label = ternary_fractions(
                record, (self.vertex_a, self.vertex_b, self.vertex_c), self.unit_choice
            )
        if not record.spectrum_action_uuid or not record.spectrum_file_name:
            async with self:
                self.error = "this process recorded no spectrum file"
            return
        try:
            series = await api.fetch_spectrum(
                api.get_client(),
                record.spectrum_action_uuid,
                record.spectrum_file_name,
            )
        except Exception as exc:
            LOGGER.warning(
                f"composition could not read the spectrum for "
                f"{record.process_uuid}: {exc}"
            )
            async with self:
                self.error = f"the spectrum could not be read: {exc}"
            return
        ev = series.get("ev") or []
        intensity = series.get("intensity") or []
        if not ev or not intensity:
            async with self:
                self.error = "the spectrum file carried no ev/intensity series"
            return
        async with self:
            self.version += 1
            payload = plots.spectra(
                ev,
                {record.global_label: intensity},
                x_label="ev",
                y_label="intensity",
                panel_id=f"{self.panel_key()}-spec",
                version=self.version,
            )
            self.spec_spec = payload.spec
            self.spec_url = payload.buffer_url
            self.spec_layout = payload.layout


def _controls():
    """The plate-id field, the four dropdowns and the two buttons."""
    return rx.vstack(
        rx.hstack(
            rx.input(
                placeholder="plate id",
                value=CompositionState.plate_id,
                on_change=CompositionState.set_plate_id,
                width="10em",
            ),
            rx.button("Retrieve", on_click=CompositionState.retrieve("")),
            rx.text(CompositionState.status, size="1"),
            spacing="3",
            align="center",
        ),
        rx.hstack(
            rx.text("run_use", size="1", class_name=reflex_muted_text_class()),
            rx.select(
                CompositionState.run_use_options,
                value=CompositionState.run_use_choice,
                on_change=CompositionState.set_run_use,
                width="12em",
            ),
            rx.text("sequence", size="1", class_name=reflex_muted_text_class()),
            rx.select(
                CompositionState.sequence_options,
                value=CompositionState.sequence_choice,
                on_change=CompositionState.set_sequence,
                width="24em",
            ),
            spacing="3",
            align="center",
        ),
        rx.hstack(
            rx.text("transition", size="1", class_name=reflex_muted_text_class()),
            rx.select(
                CompositionState.transition_options,
                value=CompositionState.transition_choice,
                on_change=CompositionState.set_transition,
                width="10em",
            ),
            rx.text("unit", size="1", class_name=reflex_muted_text_class()),
            rx.select(
                CompositionState.unit_options,
                value=CompositionState.unit_choice,
                on_change=CompositionState.set_unit,
                width="14em",
            ),
            rx.button("Plot", on_click=CompositionState.plot("")),
            spacing="3",
            align="center",
        ),
        width="100%",
        spacing="2",
    )


def _map_panel():
    """The plate map, or the note saying why there is none."""
    return rx.vstack(
        rx.hstack(
            rx.checkbox(
                "RBF interpolate",
                checked=CompositionState.interpolate,
                on_change=CompositionState.set_interpolate,
            ),
            spacing="3",
            align="center",
        ),
        rx.cond(
            CompositionState.platemap_note != "",
            rx.text(
                CompositionState.platemap_note,
                size="1",
                class_name=reflex_muted_text_class(),
            ),
            plots.chart(
                CompositionState.map_spec,
                CompositionState.map_url,
                CompositionState.map_layout,
                height=CHART_HEIGHT,
                width=plots.square_width(CHART_HEIGHT),
                on_select=CompositionState.on_map_select,
            ),
        ),
        width="100%",
        spacing="2",
    )


def _ternary_panel():
    """The ternary diagram and its three vertex selectors."""
    return rx.vstack(
        rx.hstack(
            rx.select(
                CompositionState.transition_options,
                value=CompositionState.vertex_a,
                on_change=CompositionState.set_vertex_a,
                width="9em",
            ),
            rx.select(
                CompositionState.transition_options,
                value=CompositionState.vertex_b,
                on_change=CompositionState.set_vertex_b,
                width="9em",
            ),
            rx.select(
                CompositionState.transition_options,
                value=CompositionState.vertex_c,
                on_change=CompositionState.set_vertex_c,
                width="9em",
            ),
            spacing="3",
            align="center",
        ),
        plots.chart(
            CompositionState.tern_spec,
            CompositionState.tern_url,
            CompositionState.tern_layout,
            height=CHART_HEIGHT,
            width=plots.square_width(CHART_HEIGHT),
            on_select=CompositionState.on_tern_select,
        ),
        width="100%",
        spacing="2",
    )


def _details_panel():
    """The selected sample's analysis output, and its spectrum."""
    return rx.vstack(
        rx.text(CompositionState.selected_label, size="2"),
        rx.text(CompositionState.ternary_label, size="2"),
        rx.table.root(
            rx.table.body(
                rx.foreach(
                    CompositionState.detail_rows,
                    lambda row: rx.table.row(
                        rx.foreach(row, lambda cell: rx.table.cell(cell))
                    ),
                )
            ),
            class_name=reflex_table_class("action"),
            width="100%",
        ),
        plots.chart(
            CompositionState.spec_spec,
            CompositionState.spec_url,
            CompositionState.spec_layout,
            height=300,
        ),
        width="100%",
        spacing="2",
    )


def build_page():
    """Render the composition page.

    Returns:
        rx.Component: The page body.
    """
    return rx.vstack(
        _controls(),
        rx.cond(
            CompositionState.error != "",
            rx.text(CompositionState.error, class_name="text-red-600", size="1"),
        ),
        rx.hstack(
            _map_panel(),
            _ternary_panel(),
            width="100%",
            spacing="4",
            align="start",
        ),
        _details_panel(),
        width="100%",
        spacing="4",
        padding_x="1em",
    )
