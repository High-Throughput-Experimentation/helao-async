# helao/core/tests/test_reflex_composition.py
"""CompositionState: loading, grouping, plotting and selection.

Every test here stubs the API layer. Nothing performs a request, and nothing
needs a platemap.
"""

import asyncio

import pytest

from helao.ui.reflex import composition
from helao.ui.shared.composition import grouping
from helao.ui.shared.composition.model import CompositionRecord


def record(**kwargs) -> CompositionRecord:
    base = dict(
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
    """The whole retrieve path, with the API layer stubbed."""

    async def fake_search(client, plate_id, size=500):
        return [{"process_uuid": "p1"}]

    async def fake_sequences(client, uuids):
        return {}

    async def fake_quant(client, action_uuid, file_name):
        return {
            "transition": ["Co.K", "Y.K", "Pt.L"],
            "net_counts": [271.2, 792.1, 44.7],
        }

    monkeypatch.setattr(composition.api, "search_processes", fake_search)
    monkeypatch.setattr(composition.api, "fetch_sequences", fake_sequences)
    monkeypatch.setattr(composition.api, "fetch_quant", fake_quant)
    monkeypatch.setattr(composition.api, "get_client", lambda: object())
    monkeypatch.setattr(
        composition.model,
        "record_from_process",
        lambda item, seqs: record(),
    )

    loaded = asyncio.run(composition.load_records(10244))
    assert len(loaded.records) == 1
    assert loaded.failures == 0
    assert grouping.ALL in grouping.run_use_options(loaded.records)


def test_load_counts_a_failed_quant_fetch_rather_than_raising(monkeypatch) -> None:
    """One unreadable HLO out of 497 must not cost the other 496."""

    async def fake_search(client, plate_id, size=500):
        return [{"process_uuid": "p1"}, {"process_uuid": "p2"}]

    async def fake_sequences(client, uuids):
        return {}

    calls = {"n": 0}

    async def fake_quant(client, action_uuid, file_name):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("500 from S3")
        return {"transition": ["Co.K"], "net_counts": [1.0]}

    monkeypatch.setattr(composition.api, "search_processes", fake_search)
    monkeypatch.setattr(composition.api, "fetch_sequences", fake_sequences)
    monkeypatch.setattr(composition.api, "fetch_quant", fake_quant)
    monkeypatch.setattr(composition.api, "get_client", lambda: object())
    monkeypatch.setattr(
        composition.model, "record_from_process", lambda item, seqs: record()
    )

    loaded = asyncio.run(composition.load_records(10244))
    assert loaded.failures == 1
    assert len(loaded.records) == 1


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
