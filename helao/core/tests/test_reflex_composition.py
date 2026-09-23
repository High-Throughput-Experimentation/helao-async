# helao/core/tests/test_reflex_composition.py
"""CompositionState: loading, grouping, plotting and selection.

Every test here stubs the API layer. Nothing performs a request, and nothing
needs a platemap.
"""

import asyncio
from typing import Any

from helao.ui.reflex import composition
from helao.ui.shared.composition import grouping
from helao.ui.shared.composition.model import CompositionRecord


def record(**kwargs) -> CompositionRecord:
    base: dict[str, Any] = dict(
        plate_id=10244,
        sample_no=1,
        global_label="legacy__solid__10244_1",
        run_use="post_anneal",
        sequence_uuid="06a7e382-a773-731d-8000-d7e3e21eacec",
        sequence_timestamp="2026-08-13T11:54:21.000000",
        process_uuid="p1",
        process_timestamp="2026-08-13T11:57:41.000000",
        quant_action_uuid="a1",
        quant_file_name="q.json",
        spectrum_action_uuid="a1",
        spectrum_file_name="s.json",
        values={
            "Co.K": {"net_counts": 271.2, "atomic_fraction": 0.167},
            "Y.K": {"net_counts": 792.1, "atomic_fraction": 0.814},
            "Pt.L": {"net_counts": 44.7, "atomic_fraction": 0.019},
        },
    )
    base.update(kwargs)
    return CompositionRecord(**base)


RECORDS = [record(), record(sample_no=2, run_use="pre_anneal", process_uuid="p2")]

PM_ROWS = [
    {"sample_no": 1, "x": 0.0, "y": 0.0, "entry": {}},
    {"sample_no": 2, "x": 1.0, "y": 0.0, "entry": {}},
    {"sample_no": 3, "x": 0.0, "y": 1.0, "entry": {}},
    {"sample_no": 4, "x": 1.0, "y": 1.0, "entry": {}},
    {"sample_no": 5, "x": 0.5, "y": 0.5, "entry": {}},
]


def test_plate_id_must_be_an_integer() -> None:
    assert composition.parse_plate_id("10244") == 10244
    assert composition.parse_plate_id(" 10244 ") == 10244
    assert composition.parse_plate_id("plate ten") is None
    assert composition.parse_plate_id("") is None


def test_series_for_returns_one_value_per_record_with_none_for_missing() -> None:
    """A record missing the selected transition keeps its slot: the value array
    and the position array are indexed together downstream."""
    values = composition.series_for(RECORDS, "Co.K", "net_counts")
    assert values == [271.2, 271.2]
    missing = composition.series_for(RECORDS, "Fe.K", "net_counts")
    assert missing == [None, None]


def test_map_arrays_join_on_the_platemap_sample_no() -> None:
    """Joined by the platemap's own ``sample_no``, not by list position.

    Records here carry sample numbers 5 and 2, in that order -- neither
    matches its position in this list, so a positional zip (record i paired
    with ``pm_rows[i]``) would land on the wrong platemap row for both. Only a
    join keyed on ``sample_no`` produces the coordinates asserted below.
    """
    mixed = [
        record(sample_no=5, values={"Co.K": {"net_counts": 111.0}}),
        record(sample_no=2, values={"Co.K": {"net_counts": 222.0}}),
    ]
    xs, ys, values, kept = composition.map_arrays(mixed, PM_ROWS, "Co.K", "net_counts")
    assert xs == [0.5, 1.0]
    assert ys == [0.5, 0.0]
    assert values == [111.0, 222.0]
    assert [r.sample_no for r in kept] == [5, 2]


def test_map_arrays_drops_a_record_with_no_platemap_row() -> None:
    xs, _, _, kept = composition.map_arrays(
        [record(sample_no=9999)], PM_ROWS, "Co.K", "net_counts"
    )
    assert xs == []
    assert kept == []


def test_map_arrays_drops_a_record_whose_value_is_none() -> None:
    """None is an uncalibrated transition, not zero. Plotting it as 0.0 would
    read as a measurement."""
    blank = record(sample_no=2, values={"Co.K": {"net_counts": None}})
    xs, _, values, kept = composition.map_arrays([blank], PM_ROWS, "Co.K", "net_counts")
    assert xs == []
    assert values == []
    assert kept == []


def test_detail_rows_lists_every_transition_and_unit() -> None:
    rows = composition.detail_rows(record())
    assert rows[0] == ["transition", "atomic_fraction", "net_counts"]
    assert ["Co.K", "0.167", "271.2"] in rows


def test_detail_rows_shows_a_missing_value_as_a_dash() -> None:
    rows = composition.detail_rows(record(values={"Y.L": {"atomic_fraction": None}}))
    assert ["Y.L", "-"] in rows


def test_nearest_record_picks_by_distance_in_the_plotted_plane() -> None:
    xs = [0.0, 1.0]
    ys = [0.0, 0.0]
    assert composition.nearest_record(RECORDS, xs, ys, 0.9, 0.05) is RECORDS[1]
    # Closer to the *other* point this time: guards against an implementation
    # that always returns the first or the last record regardless of distance
    # (the assertion above alone can't tell "closest" from "last").
    assert composition.nearest_record(RECORDS, xs, ys, 0.05, 0.05) is RECORDS[0]


def test_nearest_record_on_an_empty_plot_returns_none() -> None:
    assert composition.nearest_record([], [], [], 0.0, 0.0) is None


def test_load_populates_records_and_options(monkeypatch) -> None:
    """The whole retrieve path, with the API layer stubbed.

    Two records, each carrying its own distinct payload keyed by its own
    ``quant_action_uuid`` -- and the second's fetch finishes before the
    first's, so a completion-order bug in the fan-out would swap them. Only a
    correct ``zip(records, payloads)`` against ``asyncio.gather``'s
    input-ordered results pairs each record with its own value.
    """

    async def fake_search(client, plate_id, size=500):
        return [{"process_uuid": "p1"}, {"process_uuid": "p2"}]

    async def fake_sequences(client, uuids):
        return {}

    async def fake_quant(client, action_uuid, file_name):
        # a1 (p1's fetch) is slower, so a2 (p2's fetch) resolves first even
        # though p1 was listed -- and dispatched -- first.
        delay = {"a1": 0.02, "a2": 0.0}[action_uuid]
        await asyncio.sleep(delay)
        value = {"a1": 271.2, "a2": 999.0}[action_uuid]
        return {"transition": ["Co.K"], "net_counts": [value]}

    def fake_record_from_process(item, seqs):
        uuid = item["process_uuid"]
        return record(
            process_uuid=uuid,
            quant_action_uuid={"p1": "a1", "p2": "a2"}[uuid],
        )

    monkeypatch.setattr(composition.api, "search_processes", fake_search)
    monkeypatch.setattr(composition.api, "fetch_sequences", fake_sequences)
    monkeypatch.setattr(composition.api, "fetch_quant", fake_quant)
    monkeypatch.setattr(composition.api, "get_client", lambda: object())
    monkeypatch.setattr(
        composition.model, "record_from_process", fake_record_from_process
    )

    loaded = asyncio.run(composition.load_records(10244))
    assert len(loaded.records) == 2
    assert loaded.failures == 0
    by_uuid = {r.process_uuid: r for r in loaded.records}
    assert by_uuid["p1"].values["Co.K"]["net_counts"] == 271.2
    assert by_uuid["p2"].values["Co.K"]["net_counts"] == 999.0
    # run_use_options always includes ALL regardless of input -- checking for
    # its presence alone would pass even on a totally failed load. Pin the
    # exact list, which only holds if both loaded records actually made it
    # through the grouping call.
    assert grouping.run_use_options(loaded.records) == [grouping.ALL, "post_anneal"]


def test_load_counts_a_failed_quant_fetch_rather_than_raising(monkeypatch) -> None:
    """One unreadable HLO out of 497 must not cost the other 496.

    Two distinct records, the failure keyed to the *first* one's own
    ``quant_action_uuid`` -- so this pins not just the count but which record
    survived and that it carries its own (not the failed one's) value.
    """

    async def fake_search(client, plate_id, size=500):
        return [{"process_uuid": "p1"}, {"process_uuid": "p2"}]

    async def fake_sequences(client, uuids):
        return {}

    async def fake_quant(client, action_uuid, file_name):
        if action_uuid == "a1":
            raise RuntimeError("500 from S3")
        return {"transition": ["Co.K"], "net_counts": [999.0]}

    def fake_record_from_process(item, seqs):
        uuid = item["process_uuid"]
        return record(
            process_uuid=uuid,
            quant_action_uuid={"p1": "a1", "p2": "a2"}[uuid],
        )

    monkeypatch.setattr(composition.api, "search_processes", fake_search)
    monkeypatch.setattr(composition.api, "fetch_sequences", fake_sequences)
    monkeypatch.setattr(composition.api, "fetch_quant", fake_quant)
    monkeypatch.setattr(composition.api, "get_client", lambda: object())
    monkeypatch.setattr(
        composition.model, "record_from_process", fake_record_from_process
    )

    loaded = asyncio.run(composition.load_records(10244))
    assert loaded.failures == 1
    assert len(loaded.records) == 1
    assert loaded.records[0].process_uuid == "p2"
    assert loaded.records[0].values["Co.K"]["net_counts"] == 999.0


def test_configure_records_the_world_config() -> None:
    composition.configure({"servers": {}}, "UI")
    assert composition.world_config() == {"servers": {}}


def test_platemap_note_names_the_missing_piece(monkeypatch) -> None:
    """Three different causes, three different notes: the operator's next move
    differs in each."""
    monkeypatch.setattr(composition.platemap, "plate_api_for_config", lambda cfg: None)
    composition.configure({"servers": {}}, "UI")
    rows, note = composition.platemap_for(10244)
    assert rows == []
    assert "no plate API" in note


def test_platemap_note_when_access_is_unavailable(monkeypatch) -> None:
    class NoAccess:
        has_access = False

    monkeypatch.setattr(
        composition.platemap, "plate_api_for_config", lambda cfg: NoAccess()
    )
    composition.configure({"servers": {}}, "UI")
    rows, note = composition.platemap_for(10244)
    assert rows == []
    assert "HELAO_CREDENTIALS" in note


class _FakeCompositionState:
    """A stand-in carrying the vars ``plot``/``_draw_map``/``_draw_ternary``
    touch.

    Deliberately not a ``CompositionState`` subclass, for the reason
    ``test_reflex_motion_control.py``'s own ``_FakeState`` exists: Reflex
    intercepts attribute assignment on a real ``rx.State`` and forwards it to
    a session that does not exist outside a running app. The three methods
    under test are bound straight off the real class, so this exercises the
    actual clearing logic rather than a reimplementation of it.
    """

    def __init__(self):
        self.error = ""
        self.status = ""
        self._records: list = []
        self._pm_rows: list = []
        self._plotted: list = []
        self._plotted_xs: list = []
        self._plotted_ys: list = []
        self._tern_plotted: list = []
        self._tern_plotted_xs: list = []
        self._tern_plotted_ys: list = []
        self.run_use_choice = grouping.ALL
        self.sequence_choice = grouping.ALL
        self.transition_choice = ""
        self.unit_choice = ""
        self.vertex_a = ""
        self.vertex_b = ""
        self.vertex_c = ""
        self.interpolate = False
        self.version = 0
        self.map_spec: dict = {}
        self.map_url = ""
        self.map_layout = ""
        self.tern_spec: dict = {}
        self.tern_url = ""
        self.tern_layout = ""
        self.selected_label = ""
        self.ternary_label = ""
        self.overlay_spectra = False
        self.tern_color_choice = composition.NO_COLOR
        self.tern_color_options: list = [composition.NO_COLOR]
        self._spectra: list = []
        self.spec_spec: dict = {}
        self.spec_url = ""
        self.spec_layout = ""
        self.detail_rows: list = []
        self.sequence_options: list = []
        self.transition_options: list = []
        self.unit_options: list = []

    def panel_key(self) -> str:
        return "test-panel"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    # ``plot`` is wrapped in an ``EventHandler`` by ``@rx.event``; ``.fn`` is
    # the underlying plain function. ``_draw_map``/``_draw_ternary``/``_select``
    # carry no such decorator and bind directly.
    plot = composition.CompositionState.plot.fn  # type: ignore[attr-defined]
    _draw_map = composition.CompositionState._draw_map
    _draw_ternary = composition.CompositionState._draw_ternary
    _select = composition.CompositionState._select
    _refresh_options = composition.CompositionState._refresh_options
    _draw_spectra = composition.CompositionState._draw_spectra
    set_overlay_spectra = composition.CompositionState.set_overlay_spectra.fn  # type: ignore[attr-defined]
    on_tern_select = composition.CompositionState.on_tern_select.fn  # type: ignore[attr-defined]


def test_plot_clears_the_previous_charts_on_a_platemap_less_reload() -> None:
    """A retrieve for a plate with no platemap must not leave the prior
    plate's map, ternary and selectable points on screen.

    Regression for a live bug: retrieve plate A (platemap loads) -> Plot ->
    retrieve plate B (no platemap, so ``_pm_rows`` comes back empty) -> Plot.
    ``_draw_map`` returns early on an empty ``_pm_rows``, and neither it nor
    the old ``plot`` cleared what was already drawn, so plate A's map stayed
    up next to plate B's fresh ternary -- and a click on it resolved to a
    plate A record, filling the details table and fetching plate A's spectrum
    under plate B's own header. Nothing errored.
    """
    state = _FakeCompositionState()
    state._records = RECORDS
    state._pm_rows = PM_ROWS
    state.transition_choice = "Co.K"
    state.unit_choice = "net_counts"
    state.vertex_a, state.vertex_b, state.vertex_c = "Co.K", "Y.K", "Pt.L"

    state.plot()
    assert state.map_url != ""
    assert state._plotted != []
    assert state._plotted_xs != []

    # The next retrieve: a plate whose platemap did not load.
    state._pm_rows = []
    state.plot()
    assert state.map_url == ""
    assert state.map_spec == {}
    assert state.map_layout == ""
    assert state._plotted == []
    assert state._plotted_xs == []
    assert state._plotted_ys == []


def test_plot_clears_the_selected_sample_when_the_new_grouping_excludes_it() -> None:
    """Regression: retrieve -> Plot -> select sample 42 -> narrow ``run_use``
    to something matching nothing -> Plot left the details panel, its table
    and its spectrum on screen for a sample the current view no longer
    contains. Nothing errored.
    """
    state = _FakeCompositionState()
    state._records = RECORDS
    state._pm_rows = PM_ROWS
    state.transition_choice = "Co.K"
    state.unit_choice = "net_counts"
    state.vertex_a, state.vertex_b, state.vertex_c = "Co.K", "Y.K", "Pt.L"
    state.plot()

    # Simulate a prior selection, as `_select` would have set it.
    state.selected_label = "legacy__solid__10244_42   sample 42   post_anneal"
    state.detail_rows = [["transition", "net_counts"], ["Co.K", "271.2"]]
    state.spec_spec, state.spec_url, state.spec_layout = {"a": 1}, "u", "l"

    state.run_use_choice = "no-such-run-use"
    state.plot()

    assert state.status == "nothing matches this grouping"
    assert state.map_url == ""
    assert state.selected_label == ""
    assert state.detail_rows == []
    assert state.spec_spec == {}
    assert state.spec_url == ""
    assert state.spec_layout == ""


def test_draw_ternary_keeps_records_index_aligned_when_a_middle_point_is_dropped() -> (
    None
):
    """``barycentric_to_cartesian`` drops any point with a non-finite,
    negative, or zero-sum component. A dropped *middle* record is the case
    that catches an off-by-one in the surviving mask -- dropping the first or
    last point can pass even when ``_tern_plotted`` and ``_tern_plotted_xs``/
    ``_ys`` have drifted out of alignment with each other.
    """
    kept_a = record(
        sample_no=1,
        process_uuid="ka",
        values={
            "Co.K": {"net_counts": 1.0},
            "Y.K": {"net_counts": 0.0},
            "Pt.L": {"net_counts": 0.0},
        },
    )
    # Missing Co.K and Pt.L entirely: series_for returns None for both, which
    # _draw_ternary turns into NaN -- barycentric_to_cartesian drops it.
    dropped = record(
        sample_no=2,
        process_uuid="dropped",
        values={"Y.K": {"net_counts": 1.0}},
    )
    kept_b = record(
        sample_no=3,
        process_uuid="kb",
        values={
            "Co.K": {"net_counts": 0.0},
            "Y.K": {"net_counts": 0.0},
            "Pt.L": {"net_counts": 1.0},
        },
    )
    records = [kept_a, dropped, kept_b]

    state = _FakeCompositionState()
    state.vertex_a, state.vertex_b, state.vertex_c = "Co.K", "Y.K", "Pt.L"
    state.unit_choice = "net_counts"
    state._draw_ternary(records)

    assert [r.process_uuid for r in state._tern_plotted] == ["ka", "kb"]
    assert len(state._tern_plotted_xs) == 2
    assert len(state._tern_plotted_ys) == 2

    # Clicking exactly where the second surviving point landed must resolve
    # to kept_b -- an off-by-one against the dropped record's slot would
    # instead land on kept_a (the only other candidate), which a "drop the
    # first or last point" fixture could never catch.
    x, y = state._tern_plotted_xs[1], state._tern_plotted_ys[1]
    found = composition.nearest_record(
        state._tern_plotted, state._tern_plotted_xs, state._tern_plotted_ys, x, y
    )
    assert found is kept_b


def test_on_tern_select_finds_the_nearest_plotted_record_and_fills_the_details_panel() -> (
    None
):
    """Clicking the ternary must resolve against the ternary's own stored
    coordinates, not the plate map's -- ``plot()`` draws both charts, so a
    shared selection array would have one click resolve against the other
    chart's points.
    """
    near = record(
        sample_no=7,
        process_uuid="near",
        global_label="near-sample",
        spectrum_action_uuid="",
        spectrum_file_name="",
        values={
            "Co.K": {"net_counts": 1.0},
            "Y.K": {"net_counts": 0.0},
            "Pt.L": {"net_counts": 0.0},
        },
    )
    far = record(
        sample_no=8,
        process_uuid="far",
        global_label="far-sample",
        spectrum_action_uuid="",
        spectrum_file_name="",
        values={
            "Co.K": {"net_counts": 0.0},
            "Y.K": {"net_counts": 0.0},
            "Pt.L": {"net_counts": 1.0},
        },
    )
    state = _FakeCompositionState()
    state.vertex_a, state.vertex_b, state.vertex_c = "Co.K", "Y.K", "Pt.L"
    state.unit_choice = "net_counts"
    state._draw_ternary([near, far])
    assert state._tern_plotted_xs

    x, y = state._tern_plotted_xs[0], state._tern_plotted_ys[0]
    asyncio.run(state.on_tern_select({"x": x, "y": y}))

    assert state.selected_label.startswith("near-sample")
    assert state.detail_rows != []
    assert state.ternary_label.endswith("Co.K 1.000   Y.K 0.000   Pt.L 0.000")


def _chart_nodes(page) -> list:
    """Every ``XYChart`` node in the page tree, in document order."""
    charts: list = []

    def walk(node) -> None:
        if type(node).__name__ == "XYChart":
            charts.append(node)
        for child in getattr(node, "children", []) or []:
            walk(child)

    walk(page)
    return charts


def _on_select_handler_name(chart_node) -> str:
    """The bound handler's function name, out of the rendered event trigger."""
    trigger = chart_node.event_triggers["on_select"]
    return trigger.events[0].handler.fn.__name__


def test_the_ternary_chart_is_bound_to_its_own_click_handler() -> None:
    """The map and the ternary each resolve clicks against their own plotted
    points -- binding both charts to the same handler, or leaving the
    ternary's ``on_select`` unset, is exactly the bug this page shipped with
    (the ternary click path did nothing on every host and config in this
    repo, since no config here declares a plate map). The spectrum chart
    carries no ``on_select`` at all -- there is nothing to click there."""
    charts = _chart_nodes(composition.build_page())
    assert len(charts) == 3
    map_chart, tern_chart, spec_chart = charts
    assert _on_select_handler_name(map_chart) == "on_map_select"
    assert _on_select_handler_name(tern_chart) == "on_tern_select"
    assert "on_select" not in spec_chart.event_triggers


def test_build_page_renders() -> None:
    """Rendered, not merely imported. A handler bound to both a button and
    something that supplies a value raises at render, not at import, so an
    import-only test cannot see it."""
    assert composition.build_page() is not None


def test_every_foreach_var_carries_an_element_annotation() -> None:
    """A bare `list` fails the frontend build with `ForeachVarError`, which
    surfaces only at `reflex export`.

    `CompositionState.__annotations__` is unusable here: the module carries
    `from __future__ import annotations`, so every stored annotation is the
    *string* `"list[list[str]]"` rather than the type object, and a string
    never equals `list[list[str]]`. `get_fields()[name].annotated_type` is
    Reflex's own resolved-type view and is what actually gates `rx.foreach`.
    """
    fields = composition.CompositionState.get_fields()
    assert fields["detail_rows"].annotated_type == list[list[str]]
    for name in (
        "run_use_options",
        "sequence_options",
        "transition_options",
        "unit_options",
    ):
        assert fields[name].annotated_type == list[str], name


def test_platemap_note_when_the_plate_will_not_load(monkeypatch) -> None:
    class Raises:
        has_access = True

        def get_platemap_plateid(self, plate_id):
            raise RuntimeError("no such plate")

    monkeypatch.setattr(
        composition.platemap, "plate_api_for_config", lambda cfg: Raises()
    )
    composition.configure({"servers": {}}, "UI")
    rows, note = composition.platemap_for(10244)
    assert rows == []
    assert "10244" in note


def test_dropdowns_narrow_to_the_selected_run_use_and_sequence() -> None:
    """run_use scopes sequences; run_use + sequence scope transitions/units."""
    old = record(
        run_use="pre_anneal",
        sequence_uuid="11111111-0000-0000-0000-000000000000",
        sequence_timestamp="2026-07-01T00:00:00.000000",
        values={"Fe.K": {"net_counts": 1.0}},
    )
    state = _FakeCompositionState()
    state._records = [record(), old]
    state._refresh_options()
    assert len(state.sequence_options) == 3  # All + both sequences
    assert state.transition_options == ["Co.K", "Fe.K", "Pt.L", "Y.K"]

    state.run_use_choice = "pre_anneal"
    state._refresh_options()
    assert state.sequence_options == [grouping.ALL, grouping.sequence_label(old)]
    assert state.transition_options == ["Fe.K"]
    assert state.unit_options == ["net_counts"]
    assert state.transition_choice == "Fe.K"

    # A sequence the new run_use does not contain falls back to All.
    state.run_use_choice = grouping.ALL
    state.sequence_choice = grouping.sequence_label(old)
    state._refresh_options()
    assert state.transition_options == ["Fe.K"]
    state.run_use_choice = "post_anneal"
    state._refresh_options()
    assert state.sequence_choice == grouping.ALL
    assert "Fe.K" not in state.transition_options


def test_vertices_keep_offered_choices_and_refill_distinct_gaps() -> None:
    options = ["Co.K", "Pt.L", "Y.K"]
    assert composition._vertices(("Y.K", "Fe.K", ""), options) == (
        "Y.K",
        "Co.K",
        "Pt.L",
    )
    assert composition._vertices(("", "", ""), ["Co.K"]) == ("Co.K", "", "")


def test_ternary_fractions_normalize_the_three_vertices() -> None:
    vertices = ("Co.K", "Y.K", "Pt.L")
    line = composition.ternary_fractions(record(), vertices, "net_counts")
    # 271.2, 792.1, 44.7 over their sum of 1108.0
    assert line == (
        "ternary fractions (net_counts):   Co.K 0.245   Y.K 0.715   Pt.L 0.040"
    )


def test_ternary_fractions_are_empty_when_the_point_is_not_on_the_diagram() -> None:
    vertices = ("Co.K", "Y.K", "Fe.K")  # no Fe.K on the record
    assert composition.ternary_fractions(record(), vertices, "net_counts") == ""
    assert composition.ternary_fractions(record(), ("Co.K", "", "Y.K"), "x") == ""
    zero = record(values={v: {"u": 0.0} for v in ("A", "B", "C")})
    assert composition.ternary_fractions(zero, ("A", "B", "C"), "u") == ""


def test_overlay_toggle_accumulates_spectra_and_off_keeps_the_last(
    monkeypatch,
) -> None:
    async def fake_spectrum(client, action_uuid, file_name):
        return {"ev": [1.0, 2.0, 3.0], "intensity": [5.0, 6.0, 7.0]}

    monkeypatch.setattr(composition.api, "get_client", lambda: None)
    monkeypatch.setattr(composition.api, "fetch_spectrum", fake_spectrum)
    first, second = record(), record(sample_no=2, process_uuid="p2")
    state = _FakeCompositionState()

    def labels():
        return [t["name"] for t in state.spec_spec["traces"]]

    asyncio.run(state._select(first))
    asyncio.run(state._select(second))
    assert labels() == ["sample 2 post_anneal"]  # off: only the last

    state.set_overlay_spectra(True)
    asyncio.run(state._select(first))
    asyncio.run(state._select(first))  # a repeat is not drawn twice
    assert labels() == ["sample 2 post_anneal", "sample 1 post_anneal"]

    state.set_overlay_spectra(False)
    assert labels() == ["sample 1 post_anneal"]


def test_total_for_sums_every_transition_and_is_none_when_absent() -> None:
    assert composition.total_for(record(), "net_counts") == 271.2 + 792.1 + 44.7
    assert composition.total_for(record(), "nanomoles") is None


def test_ternary_color_options_follow_the_units_present() -> None:
    state = _FakeCompositionState()
    state.tern_color_choice = ""
    state._records = [record(values={"Co.K": {"nanomoles": 1.0}})]
    state._refresh_options()
    assert state.tern_color_options == [composition.NO_COLOR, "total nanomoles"]
    assert state.tern_color_choice == "total nanomoles"  # defaults to a total

    state._records = [record()]  # no nanomoles unit at all
    state._refresh_options()
    assert state.tern_color_options == [composition.NO_COLOR]
    assert state.tern_color_choice == composition.NO_COLOR


def test_ternary_colours_by_total_and_drops_samples_without_one() -> None:
    def rec(n, nanomoles):
        values = {
            v: {"atomic_fraction": 1 / 3, "nanomoles": nanomoles}
            for v in ("A", "B", "C")
        }
        return record(sample_no=n, process_uuid=f"p{n}", values=values)

    missing = rec(2, None)
    records = [rec(1, 1.0), missing, rec(3, 2.0)]
    state = _FakeCompositionState()
    state.vertex_a, state.vertex_b, state.vertex_c = "A", "B", "C"
    state.unit_choice = "atomic_fraction"
    state.tern_color_choice = "total nanomoles"
    state._draw_ternary(records)

    # Clickable points and plotted points stay index-aligned.
    assert [r.sample_no for r in state._tern_plotted] == [1, 3]
    samples = next(t for t in state.tern_spec["traces"] if t["name"] == "samples")
    assert samples["color"]["mode"] == "continuous"
    assert state.tern_spec["tooltip"]["labels"] == {"color": "total nanomoles"}

    state.tern_color_choice = composition.NO_COLOR
    state._draw_ternary(records)
    assert len(state._tern_plotted) == 3
