"""Tests for the `/xrds` page: records, pattern choice, window statistics."""

import numpy as np
import pytest

from helao.ui.reflex import xrds as page
from helao.ui.shared import spectra, xrds
from helao.ui.shared.composition import grouping

TTH = np.linspace(10.0, 63.0, 5301)  # 0.01 deg grid
ORIGINAL = xrds.FILE_TYPES["original"]
BKGSUB = xrds.FILE_TYPES["background subtracted"]


def _item(n, seq="s1", run_use="data"):
    return {
        "process_name": "xrds_frame",
        "process_uuid": f"p{n}",
        "sequence_uuid": seq,
        "run_use": run_use,
        "process_params": {
            "plate_id": 10211,
            "sample_no": n,
            "global_label": f"legacy__solid__10211_{n}",
        },
        "files": [
            {
                "file_type": "bruker_gadds_frames__nexus_file",
                "file_name": "f.nxs",
                "action_uuid": "a",
            },
            {"file_type": ORIGINAL, "file_name": f"o{n}.hlo", "action_uuid": f"a{n}"},
            {"file_type": BKGSUB, "file_name": f"b{n}.hlo", "action_uuid": f"a{n}"},
        ],
    }


def test_each_frame_yields_one_record_per_pattern_with_distinct_keys() -> None:
    sequences = {"s1": {"sequence_timestamp": "2026-08-31T10:00:00"}}
    records = xrds.records_from_processes(
        [_item(1), {**_item(2), "process_name": "R_UVVIS"}], sequences
    )
    assert [(r.sample_no, r.file_type) for r in records] == [(1, ORIGINAL), (1, BKGSUB)]
    assert records[0].spectrum_key != records[1].spectrum_key
    assert records[0].sequence_timestamp == "2026-08-31T10:00:00"
    no_sample = {**_item(3), "process_params": {"plate_id": 10211}}
    assert xrds.records_from_processes([no_sample]) == []


def test_selection_takes_one_pattern_type() -> None:
    records = xrds.records_from_processes([_item(1), _item(2, run_use="ref")])
    chosen = page.select_records(records, "data", grouping.ALL, BKGSUB)
    assert [(r.sample_no, r.file_type) for r in chosen] == [(1, BKGSUB)]


class _FakeXrdsState:
    def __init__(self, records):
        self._loaded = records
        self._pm_rows = [
            {"sample_no": r.sample_no, "x": float(r.sample_no), "y": 0.0, "entry": {}}
            for r in records
        ]
        self._plotted, self._plotted_xs, self._plotted_ys = [], [], []
        self._selected = []
        self.wl_min, self.wl_max = float(TTH.min()), float(TTH.max())
        self.wl_lo, self.wl_hi = 30.0, 31.0
        self.overlay_spectra = False
        self.point_scale = 1.0
        self.selected_label = ""
        self.detail_rows = []
        self.version = 0
        for name in ("map", "hist", "spec"):
            setattr(self, f"{name}_spec", {})
            setattr(self, f"{name}_url", "")
            setattr(self, f"{name}_layout", "")

    def panel_key(self):
        return "test-xrds"

    for _name in ("X_LABEL", "Y_LABEL", "Y_NAME", "X_UNIT", "STATS_RANGE", "DECIMALS"):
        locals()[_name] = getattr(page.XrdsState, _name)
    _draw = page.XrdsState._draw
    _draw_map = page.XrdsState._draw_map
    _draw_histogram = page.XrdsState._draw_histogram
    _draw_spectra = page.XrdsState._draw_spectra
    _window_label = page.XrdsState._window_label
    _x_label = page.XrdsState._x_label
    _y_label = page.XrdsState._y_label
    _y_name = page.XrdsState._y_name
    _x_unit = page.XrdsState._x_unit
    _redraw = page.XrdsState._redraw
    on_map_select = page.XrdsState.on_map_select.fn  # type: ignore[attr-defined]


def test_patterns_of_both_types_cache_apart_and_plot_by_two_theta() -> None:
    spectra.reset_cache()
    records = xrds.records_from_processes([_item(1), _item(2)])
    for r in records:
        scale = 1.0 if r.file_type == ORIGINAL else 0.5
        spectra.store(r.spectrum_key, TTH, TTH * r.sample_no * scale)
    bkgsub = [r for r in records if r.file_type == BKGSUB]
    state = _FakeXrdsState(bkgsub)
    state._draw()
    axes = {a["id"]: a.get("label") for a in state.spec_spec["axes"].values()}
    assert axes == {"x": "twotheta_deg", "y": "intensity_au"}
    assert state.map_spec["colorbar"]["label"] == "mean intensity 30.00-31.00 deg"
    state.on_map_select({"x": 2.0, "y": 0.0})  # sample 2, bkgsub: y = tth
    rows = dict(map(tuple, state.detail_rows[1:]))
    assert rows["window mean (30.00-31.00 deg)"] == "30.5"
    assert rows["min (window)"] == "30" and rows["max (window)"] == "31"
    spectra.reset_cache()


def test_cache_is_bounded_by_bytes(monkeypatch) -> None:
    spectra.reset_cache()
    monkeypatch.setattr(spectra, "_CACHE_BYTES", 3 * 2 * 4 * 100)  # 3 spectra
    for n in range(5):
        spectra.store(f"k{n}", np.zeros(100), np.zeros(100))
    assert [spectra.cached_spectrum(f"k{n}") is not None for n in range(5)] == [
        False,
        False,
        True,
        True,
        True,
    ]
    spectra.reset_cache()
