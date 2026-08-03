"""Tests for the hte deployment's Reflex live panels.

The four live visualizers share one shape, so the logic that can be wrong lives
in ``servers/reflex/_live.py`` and is tested here directly. Nothing that only
runs inside a Reflex app is reachable from a unit test -- the panels themselves
are verified in a browser.
"""

import numpy as np

from helao.deploy.hte.servers.reflex import _live

# -- rolling mean ------------------------------------------------------------


def test_a_window_shorter_than_the_filter_is_returned_unchanged():
    """Matches the Bokeh visualizers' `len(mvec) >= FWIN` guard: with less
    history than the filter width they plot the raw values rather than a mean
    computed from too little data."""
    values = np.arange(5.0)
    assert np.array_equal(_live.rolling_mean(values, window=20), values)


def test_a_full_window_is_smoothed():
    values = np.array([0.0, 10.0] * 20)
    smoothed = _live.rolling_mean(values, window=20)
    assert smoothed.shape == values.shape
    # An alternating signal averages toward its midpoint.
    assert 3.0 < smoothed[10] < 7.0


def test_a_constant_signal_is_unchanged_by_the_mean():
    values = np.full(50, 7.0)
    assert np.allclose(_live.rolling_mean(values, window=20), 7.0)


def test_an_empty_array_stays_empty():
    assert _live.rolling_mean(np.empty(0), window=20).size == 0


def test_the_mean_never_changes_the_length():
    """The mean column is plotted against the same x as its source; a shorter
    array would raise from inside plots."""
    for size in (1, 19, 20, 21, 100):
        values = np.arange(float(size))
        assert _live.rolling_mean(values, window=20).size == size


# -- column selection --------------------------------------------------------


def test_mean_name_matches_the_bokeh_column():
    assert _live.mean_name("co2_ppm") == "co2_ppm_mean"


def test_suffix_matcher_selects_only_the_named_suffixes():
    wants = _live.suffix_matcher("__mass_flow", "__pressure")
    assert wants("MFC0__mass_flow") is True
    assert wants("MFC0__pressure") is True
    assert wants("MFC0__temperature") is False


def test_every_column_matcher_takes_them_all():
    assert _live.every_column("anything") is True


def test_no_column_matcher_takes_none():
    assert _live.no_column("anything") is False


# -- series extraction -------------------------------------------------------


def _snap(**cols):
    return {k: np.asarray(v, dtype=float) for k, v in cols.items()}


def test_series_for_excludes_the_x_column():
    x, series = _live.series_for(_snap(epoch=[1, 2], co2_ppm=[400, 401]))
    assert list(x) == [1.0, 2.0]
    assert set(series) == {"co2_ppm"}


def test_series_for_appends_the_requested_means():
    snap = _snap(epoch=list(range(30)), co2_ppm=[400.0] * 30)
    _, series = _live.series_for(snap, wants_mean=_live.suffix_matcher("co2_ppm"))
    assert set(series) == {"co2_ppm", "co2_ppm_mean"}


def test_series_for_computes_no_means_by_default():
    snap = _snap(epoch=[1, 2], t=[20.0, 21.0])
    _, series = _live.series_for(snap)
    assert set(series) == {"t"}


def test_series_for_does_not_recompute_a_mean_the_stream_already_carries():
    """Some drivers publish their own `_mean` column. Recomputing over it would
    plot a mean of a mean under the same name."""
    snap = _snap(epoch=[1, 2], p=[1.0, 2.0], p_mean=[9.0, 9.0])
    _, series = _live.series_for(snap, wants_mean=_live.every_column)
    assert list(series["p_mean"]) == [9.0, 9.0]


def test_series_for_never_takes_the_mean_of_a_mean():
    snap = _snap(epoch=[1], p=[1.0], p_mean=[1.0])
    _, series = _live.series_for(snap, wants_mean=_live.every_column)
    assert "p_mean_mean" not in series


def test_series_for_on_an_empty_snapshot():
    x, series = _live.series_for({})
    assert x.size == 0
    assert series == {}


def test_series_for_without_an_epoch_column():
    """A buffer that has not seen a message yet has no columns at all; the
    panel must render an empty chart rather than raise."""
    x, series = _live.series_for(_snap(co2_ppm=[400.0]))
    assert x.size == 0
    assert set(series) == {"co2_ppm"}


def test_series_is_ordered_for_a_stable_legend():
    """Column order comes from a dict whose insertion order follows the
    stream. A legend that reshuffles between ticks is unreadable."""
    _, series = _live.series_for(_snap(epoch=[1], b=[1.0], a=[2.0]))
    assert list(series) == ["a", "b"]


# -- latest-value table ------------------------------------------------------


def test_latest_rows_show_the_last_value_of_each_series():
    rows = _live.latest_rows({"a": np.array([1.0, 2.5]), "b": np.array([3.0])})
    assert rows == [["a", "2.5"], ["b", "3"]]


def test_latest_rows_skip_an_empty_series():
    assert _live.latest_rows({"a": np.empty(0)}) == []


def test_latest_rows_are_all_strings():
    """Reflex serialises state to JSON and rx.foreach needs list[list[str]]."""
    rows = _live.latest_rows({"a": np.array([1.0])})
    assert all(isinstance(cell, str) for row in rows for cell in row)


# -- the panels themselves ---------------------------------------------------


def test_every_live_panel_exposes_the_contract():
    """A panel missing one of these fails at render time inside the page, not
    at import, so the check is worth making explicitly."""
    from helao.deploy.hte.servers.reflex import co2_vis, mfc_vis, pressure_vis, temp_vis

    for module in (co2_vis, mfc_vis, pressure_vis, temp_vis):
        assert module.WS_PATH == "ws_live"
        assert callable(module.build)
        assert getattr(module.STATE_BASE, "_mixin", False), module.__name__


def test_each_panel_declares_its_own_axis_label():
    from helao.deploy.hte.servers.reflex import co2_vis, mfc_vis, pressure_vis, temp_vis

    labels = {module.Y_LABEL for module in (co2_vis, mfc_vis, pressure_vis, temp_vis)}
    assert len(labels) == 4


def test_the_panels_do_not_share_a_state_class():
    """A var declared on a concrete rx.State is shared by every substate under
    it; each panel needs its own mixin."""
    from helao.deploy.hte.servers.reflex import co2_vis, temp_vis

    assert co2_vis.STATE_BASE is not temp_vis.STATE_BASE


def test_panel_ids_are_distinct_per_panel_and_session():
    from helao.deploy.hte.servers.reflex import co2_vis, temp_vis

    assert co2_vis.panel_id("CO2", "tok") != temp_vis.panel_id("CO2", "tok")
    assert co2_vis.panel_id("CO2", "tok-a") != co2_vis.panel_id("CO2", "tok-b")


def test_no_panel_imports_xy_directly():
    """Only plots.py and xy_component.py may import xy."""
    import pathlib

    panel_dir = pathlib.Path(_live.__file__).parent
    for path in panel_dir.glob("*.py"):
        source = path.read_text()
        assert "import xy" not in source, path.name
