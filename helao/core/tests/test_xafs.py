"""Tests for the `/xafs` page: plate lookup, grouping, window statistics."""

import asyncio

import numpy as np
import pytest

from helao.ui.reflex import xafs as page
from helao.ui.shared import spectra, xafs
from helao.ui.shared.composition import grouping

ENERGY = np.linspace(8800.0, 9600.0, 801)  # 1 eV grid


def _proc(n, element="Cu", run_use="data", seq="s1", plate=10131):
    return {
        "process_name": "xafs_nostds",
        "process_uuid": f"{seq}-{element}-{n}",
        "sequence_uuid": seq,
        "run_use": run_use,
        "process_params": {"element": element},
        "samples_in": [
            {
                "plate_id": plate,
                "sample_no": n,
                "global_label": f"legacy__solid__{plate}_{n}",
            }
        ],
        "files": [
            {
                "file_type": "xafsmca__npz_file",
                "file_name": "m.npz",
                "action_uuid": "x",
            },
            {
                "file_type": "xafsscan__helao_file",
                "file_name": f"{n}.hlo",
                "action_uuid": f"a{n}",
            },
        ],
    }


def test_records_carry_element_and_need_a_scan_on_this_plate() -> None:
    procs = [_proc(1), _proc(2, "Co"), _proc(3, plate=999), {**_proc(4), "files": []}]
    records = xafs.records_from_processes(procs, 10131, "2026-05-07T16:00:00")
    assert [(r.sample_no, r.element, r.file_name) for r in records] == [
        (1, "Cu", "1.hlo"),
        (2, "Co", "2.hlo"),
    ]
    assert records[0].sequence_timestamp == "2026-05-07T16:00:00"


class _Client:
    """A metadata API with one indexed sequence and three found only by name:
    one naming the plate in sequence_params, one naming another plate, and
    one naming none (resolved from its processes' samples_in)."""

    def __init__(self):
        self.sequence_reads = 0

    async def search(self, request_body):
        field = request_body["filters"][0]["field"]
        if field == "sequence_params.plate_id":
            items = [{"sequence_uuid": "indexed", "sequence_timestamp": "t0"}]
        else:
            items = [
                {"sequence_uuid": u, "sequence_timestamp": "t"}
                for u in ("named", "other", "noparam")
            ]
        return {"items": items, "total": len(items)}

    async def read_sequence(self, sequence_uuid):
        self.sequence_reads += 1
        plate = {"named": 10131, "other": 42}.get(sequence_uuid)
        return {"sequence_params": {} if plate is None else {"plate_id": plate}}

    async def read_processes_by_sequence(self, sequence_uuid):
        return [_proc(7, seq=sequence_uuid)]


def test_plate_lookup_unions_the_index_with_a_cached_sequence_scan() -> None:
    xafs.reset_sequence_plates()
    client = _Client()
    found = asyncio.run(xafs.sequences_for_plate(client, 10131))
    assert sorted(s["sequence_uuid"] for s in found) == ["indexed", "named", "noparam"]
    reads = client.sequence_reads
    asyncio.run(xafs.sequences_for_plate(client, 10131))
    assert client.sequence_reads == reads  # resolved plates are cached
    xafs.reset_sequence_plates()


def test_selection_needs_one_element_and_options_cascade() -> None:
    records = xafs.records_from_processes(
        [_proc(1), _proc(2, "Co"), _proc(3, run_use="izero"), _proc(4, seq="s2")],
        10131,
    )
    assert page.element_options(records) == ["Co", "Cu"]
    chosen = page.select_records(records, "data", grouping.ALL, "Cu")
    assert sorted(r.sample_no for r in chosen) == [1, 4]


class _FakeXafsState:
    def __init__(self, records):
        self._records = records
        self._loaded = records
        self._pm_rows = [
            {"sample_no": r.sample_no, "x": float(i), "y": 0.0, "entry": {}}
            for i, r in enumerate(records)
        ]
        self._plotted, self._plotted_xs, self._plotted_ys = [], [], []
        self._selected = []
        self.wl_min, self.wl_max = float(ENERGY.min()), float(ENERGY.max())
        self.wl_lo, self.wl_hi = 9000.0, 9100.0
        self.wl_lo_text = self.wl_hi_text = ""
        self.overlay_spectra = False
        self.point_scale = 1.0
        self.selected_label = ""
        self.detail_rows = []
        self.version = 0
        self.run_use_choice = grouping.ALL
        self.sequence_choice = grouping.ALL
        self.element_choice = ""
        self.sequence_options, self.element_options = [], []
        for name in ("map", "hist", "spec"):
            setattr(self, f"{name}_spec", {})
            setattr(self, f"{name}_url", "")
            setattr(self, f"{name}_layout", "")

    def panel_key(self):
        return "test-xafs"

    FILE_TYPE = page.XafsState.FILE_TYPE
    X_LABEL = page.XafsState.X_LABEL
    Y_LABEL = page.XafsState.Y_LABEL
    Y_NAME = page.XafsState.Y_NAME
    X_UNIT = page.XafsState.X_UNIT
    STATS_RANGE = page.XafsState.STATS_RANGE
    _draw = page.XafsState._draw
    _draw_map = page.XafsState._draw_map
    _draw_histogram = page.XafsState._draw_histogram
    _draw_spectra = page.XafsState._draw_spectra
    _window_label = page.XafsState._window_label
    _redraw = page.XafsState._redraw
    _refresh_options = page.XafsState._refresh_options
    on_map_select = page.XafsState.on_map_select.fn  # type: ignore[attr-defined]


@pytest.fixture
def loaded():
    spectra.reset_cache()
    records = xafs.records_from_processes([_proc(1), _proc(2)], 10131)
    for r in records:
        spectra.store(r.process_uuid, ENERGY, ENERGY * r.sample_no)
    yield records
    spectra.reset_cache()


def test_axes_are_energy_and_roi_count_rate(loaded) -> None:
    state = _FakeXafsState(loaded)
    state._draw()
    axes = {a["id"]: a.get("label") for a in state.spec_spec["axes"].values()}
    assert axes == {"x": "Energy(eV)", "y": "ROI_CountsPerLive(C/s)"}
    assert state.map_spec["colorbar"]["label"] == "mean ROI count rate 9000.0-9100.0 eV"


def test_details_take_statistics_over_the_energy_window(loaded) -> None:
    state = _FakeXafsState(loaded)
    state._draw()
    state.on_map_select({"x": 1.0, "y": 0.0})  # sample 2: y = 2 * energy
    rows = dict(map(tuple, state.detail_rows[1:]))
    assert rows["window mean (9000.0-9100.0 eV)"] == "18100"
    assert rows["min (window)"] == "18000"
    assert rows["max (window)"] == "18200"
    assert rows["mean (window)"] == "18100"
    assert float(rows["stdev (window)"]) == pytest.approx(
        np.std(2 * np.arange(9000.0, 9101.0)), rel=1e-5
    )


def test_element_choice_falls_back_when_the_sequence_lacks_it() -> None:
    records = xafs.records_from_processes(
        [_proc(1, "Cu", seq="s1"), _proc(2, "Co", seq="s2")], 10131
    )
    records = [
        type(r)(**{**r.__dict__, "sequence_timestamp": ts})
        for r, ts in zip(records, ("2026-05-01T00:00:00", "2026-05-02T00:00:00"))
    ]
    state = _FakeXafsState(records)
    state.element_choice = "Cu"
    state._refresh_options()
    assert state.element_options == ["Co", "Cu"]
    state.sequence_choice = grouping.sequence_label(records[1])  # the Co sequence
    state._refresh_options()
    assert state.element_options == ["Co"] and state.element_choice == "Co"
