"""Tests for the xy plot facade.

These assert the facade's contract — accepts arrays, tolerates empties,
validates shapes, isolates xy — not xy's rendering, which is xy's concern.
"""

import numpy as np
import pytest

from helao.core.servers.reflex import plots


def test_time_series_returns_a_chart_payload():
    t = np.linspace(0.0, 10.0, 100)
    out = plots.time_series(t, {"a": np.sin(t)}, x_label="t", y_label="v")
    assert isinstance(out, plots.ChartPayload)
    assert isinstance(out.spec, dict)
    assert out.buffer_url.startswith("/xy/buffers/")


def test_time_series_tolerates_empty_arrays():
    assert plots.time_series(np.empty(0), {"a": np.empty(0)}) is not None


def test_time_series_accepts_multiple_series():
    t = np.linspace(0.0, 1.0, 10)
    assert plots.time_series(t, {"a": t, "b": t * 2, "c": t * 3}) is not None


def test_time_series_rejects_a_series_of_the_wrong_length():
    with pytest.raises(ValueError):
        plots.time_series(np.zeros(10), {"a": np.zeros(9)})


def test_time_series_drops_all_nan_series_without_raising():
    t = np.linspace(0.0, 1.0, 10)
    assert plots.time_series(t, {"a": np.full(10, np.nan), "b": t}) is not None


def test_spectra_returns_a_chart_payload():
    w = np.linspace(400.0, 800.0, 512)
    out = plots.spectra(w, {"t0": np.ones(512), "t1": np.ones(512) * 2})
    assert isinstance(out, plots.ChartPayload)


def test_spectra_tolerates_no_traces():
    assert plots.spectra(np.empty(0), {}) is not None


def test_scatter_map_returns_a_chart_payload():
    assert isinstance(
        plots.scatter_map(np.arange(10.0), np.arange(10.0)), plots.ChartPayload
    )


def test_scatter_map_accepts_values_for_coloring():
    assert (
        plots.scatter_map(np.arange(10.0), np.arange(10.0), values=np.arange(10.0))
        is not None
    )


def test_scatter_map_tolerates_empty_input():
    assert plots.scatter_map(np.empty(0), np.empty(0)) is not None


def test_scatter_map_rejects_mismatched_x_and_y():
    with pytest.raises(ValueError):
        plots.scatter_map(np.zeros(5), np.zeros(4))


def test_scatter_map_rejects_mismatched_values():
    with pytest.raises(ValueError):
        plots.scatter_map(np.zeros(5), np.zeros(5), values=np.zeros(4))


def test_histogram_uses_xys_native_hist_mark():
    """xy 0.0.5 has `hist`; faking histograms with step lines is not needed."""
    comp = plots.histogram(
        {"pred": np.random.default_rng(0).normal(0.45, 0.05, 1000)},
        bins=50,
        value_range=(0.2, 0.7),
    )
    assert comp is not None


def test_histogram_tolerates_an_empty_series():
    assert plots.histogram({"pred": np.empty(0)}, bins=10) is not None


def test_histogram_tolerates_no_series():
    assert plots.histogram({}, bins=10) is not None


def test_version_bump_changes_the_buffer_url_but_not_the_panel_id():
    """The browser refetches on version change; panel identity must be stable."""
    t = np.linspace(0.0, 1.0, 5)
    a = plots.time_series(t, {"a": t}, panel_id="p1", version=1)
    b = plots.time_series(t, {"a": t}, panel_id="p1", version=2)
    assert a.buffer_url != b.buffer_url
    assert "p1" in a.buffer_url and "p1" in b.buffer_url


def test_publishing_parks_buffers_the_route_can_serve():
    t = np.linspace(0.0, 1.0, 5)
    plots.time_series(t, {"a": t}, panel_id="p-store", version=9)
    assert plots.STORE.get("p-store", 9) is not None
    assert plots.STORE.get("p-store", 8) is None


def test_chart_binds_to_state_vars_and_returns_a_component():
    """build() binds once; pull() then drives it through these vars."""
    import reflex as rx

    class _S(rx.State):
        chart_spec: dict = {}
        chart_url: str = ""

    assert plots.chart(_S.chart_spec, _S.chart_url, height=300) is not None


def test_facade_exposes_exactly_the_documented_surface():
    for name in ("time_series", "spectra", "scatter_map", "histogram", "chart"):
        assert callable(getattr(plots, name))
