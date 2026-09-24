"""Tests for the `/uvvis` page's state logic, without a running app."""

import numpy as np
import pytest

from helao.ui.reflex import plots
from helao.ui.reflex import uvvis as page
from helao.ui.shared import uvvis
from helao.ui.shared.composition import grouping

WL = np.linspace(300.0, 1100.0, 801)
RUN = "06ab5756-81ff-733a-8000-81043372c76c"

PM_ROWS = [{"sample_no": n, "x": float(n), "y": 0.0, "entry": {}} for n in (1, 2, 3)]


def _record(n, run_use="data"):
    return uvvis.UvvisRecord(
        plate_id=10201,
        sample_no=n,
        global_label=f"legacy__solid__10201_{n}",
        run_id=RUN,
        run_use=run_use,
        sequence_uuid="s1",
        process_uuid=f"p{n}",
        action_uuid=f"a{n}",
        file_name=f"f{n}.parquet",
    )


@pytest.fixture
def loaded():
    """Three samples whose intensity is n * wavelength, cached."""
    uvvis.reset_cache()
    records = [_record(n) for n in (1, 2, 3)]
    for r in records:
        uvvis._store(r.process_uuid, WL, WL * r.sample_no)
    yield records
    uvvis.reset_cache()


class _FakeUvvisState:
    """Carries the vars the drawing and selection code touches; methods are
    bound off the real class, as in the composition page's tests."""

    def __init__(self, records):
        self._records = records
        self._loaded = records
        self._pm_rows = PM_ROWS
        self._plotted, self._plotted_xs, self._plotted_ys = [], [], []
        self._selected = []
        self.wl_min, self.wl_max = float(WL.min()), float(WL.max())
        self.wl_lo = self.wl_hi = 700.0
        self.wl_lo_text = self.wl_hi_text = ""
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
        return "test-uvvis"

    # The page's class-level settings, as the real state carries them.
    FILE_TYPE = page.UvvisState.FILE_TYPE
    X_LABEL = page.UvvisState.X_LABEL
    Y_LABEL = page.UvvisState.Y_LABEL
    Y_NAME = page.UvvisState.Y_NAME
    X_UNIT = page.UvvisState.X_UNIT
    STATS_RANGE = page.UvvisState.STATS_RANGE

    _draw = page.UvvisState._draw
    _draw_map = page.UvvisState._draw_map
    _draw_histogram = page.UvvisState._draw_histogram
    _draw_spectra = page.UvvisState._draw_spectra
    _window_label = page.UvvisState._window_label
    _set_window = page.UvvisState._set_window
    _redraw = page.UvvisState._redraw
    commit_wl_lo = page.UvvisState.commit_wl_lo.fn  # type: ignore[attr-defined]
    commit_wl_hi = page.UvvisState.commit_wl_hi.fn  # type: ignore[attr-defined]
    set_wl_lo_text = page.UvvisState.set_wl_lo_text.fn  # type: ignore[attr-defined]
    apply_wl_text = page.UvvisState.apply_wl_text.fn  # type: ignore[attr-defined]
    on_map_select = page.UvvisState.on_map_select.fn  # type: ignore[attr-defined]
    set_overlay_spectra = page.UvvisState.set_overlay_spectra.fn  # type: ignore[attr-defined]


def test_run_use_defaults_to_data_and_selects_within_one_run() -> None:
    records = [_record(1), _record(2, "ref_dark"), _record(3)]
    other = uvvis.UvvisRecord(**{**_record(4).__dict__, "run_id": "other"})
    options = page.run_use_options(records + [other], RUN)
    assert options == [grouping.ALL, "data", "ref_dark"]
    assert [
        r.sample_no for r in page.select_records(records + [other], RUN, "data")
    ] == [1, 3]
    assert len(page.select_records(records + [other], RUN, grouping.ALL)) == 3


def test_map_colours_by_window_mean_and_histogram_holds_them(loaded) -> None:
    state = _FakeUvvisState(loaded)
    state._draw()
    samples = state.map_spec["traces"][0]
    assert samples["color"]["mode"] == "continuous"
    assert samples["color"]["colormap"] == "magma"
    # Intensity n * wl, window at 700 nm: means 700, 1400, 2100.
    assert samples["color"]["domain"] == pytest.approx([700.0, 2100.0])
    assert state.map_spec["colorbar"]["label"] == "mean intensity 700.0-700.0 nm"
    assert [t["kind"] for t in state.hist_spec["traces"]] == ["histogram"]


def test_spectrum_chart_keeps_average_and_window_under_the_selection(loaded) -> None:
    state = _FakeUvvisState(loaded)
    state._draw()
    names = [t["name"] for t in state.spec_spec["traces"]]
    assert names == ["average"]
    bands = [
        a for a in state.spec_spec.get("annotations") or [] if a.get("kind") == "band"
    ]
    assert len(bands) == 1  # a zero-width window still shows a band

    state.on_map_select({"x": 2.0, "y": 0.0})
    names = [t["name"] for t in state.spec_spec["traces"]]
    assert names == ["average", "sample 2 data"]
    average = state.spec_spec["traces"][0]
    assert average["style"]["color"] == plots.AVERAGE_SPECTRUM
    selected = state.spec_spec["traces"][1]
    ring = next(
        t for t in state.map_spec["traces"] if t["name"].startswith("selected_")
    )
    assert selected["style"]["color"] == ring["style"]["stroke"]


def test_window_edges_move_the_colouring_and_the_band(loaded) -> None:
    state = _FakeUvvisState(loaded)
    state._draw()
    before = state.spec_layout
    state.commit_wl_lo([500.0])
    state.commit_wl_hi([600.0])
    assert state.map_spec["traces"][0]["color"]["domain"] == pytest.approx(
        [550.0, 1650.0]
    )
    assert state.spec_layout != before  # the band moved, so the chart rebuilds
    state.set_wl_lo_text("5000")  # typed past the grid: clamped to its end
    state.apply_wl_text()
    assert state.wl_lo == pytest.approx(state.wl_max)
    state.set_wl_lo_text("junk")
    state.apply_wl_text()
    assert state.wl_lo == pytest.approx(state.wl_max)  # unparsable reverts


def test_details_show_window_mean_and_350_to_1000_stats(loaded) -> None:
    state = _FakeUvvisState(loaded)
    state._draw()
    state.on_map_select({"x": 3.0, "y": 0.0})
    rows = dict(map(tuple, state.detail_rows[1:]))
    assert rows["window mean (700.0-700.0 nm)"] == "2100"
    assert rows["min (350-1000 nm)"] == "1050"
    assert rows["max (350-1000 nm)"] == "3000"
    assert rows["mean (350-1000 nm)"] == "2025"


def test_overlay_keeps_each_selection_in_its_own_colour(loaded) -> None:
    state = _FakeUvvisState(loaded)
    state._draw()
    state.set_overlay_spectra(True)
    state.on_map_select({"x": 1.0, "y": 0.0})
    state.on_map_select({"x": 3.0, "y": 0.0})
    spectra = [t["style"]["color"] for t in state.spec_spec["traces"][1:]]
    rings = [
        t["style"]["stroke"]
        for t in state.map_spec["traces"]
        if t["name"].startswith("selected_")
    ]
    assert len(set(spectra)) == 2 and spectra == rings
    state.set_overlay_spectra(False)
    assert [t["name"] for t in state.spec_spec["traces"]] == [
        "average",
        "sample 3 data",
    ]
