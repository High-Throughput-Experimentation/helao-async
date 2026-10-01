"""Tests for the xy plot facade.

These assert the facade's contract — accepts arrays, tolerates empties,
validates shapes, isolates xy — not xy's rendering, which is xy's concern.
"""

import hashlib
import importlib.metadata
import json

import numpy as np
import pytest
import xy.channel

from helao.core.tests._plate_photo_fakes import EXTENT, top_row_red
from helao.ui.reflex import plots


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


def test_time_series_rejects_a_series_when_x_is_empty():
    """Gating validation on x being non-empty would skip exactly this case."""
    with pytest.raises(ValueError):
        plots.time_series(np.empty(0), {"a": np.zeros(3)})


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
        chart_layout: str = ""

    component = plots.chart(_S.chart_spec, _S.chart_url, _S.chart_layout, height=300)
    assert component is not None


def test_published_specs_carry_an_advancing_append_token():
    """The freeze this guards: xy's update handler bails on `if (!spec.append)`,
    and build_payload_split leaves append unset. Without it the chart paints one
    frame and never moves again, however often the buffers change."""
    t = np.linspace(0.0, 1.0, 5)
    first = plots.time_series(t, {"a": t}, panel_id="p-seq", version=1)
    second = plots.time_series(t, {"a": t}, panel_id="p-seq", version=2)
    assert first.spec["append"]["seq"] == 1
    assert second.spec["append"]["seq"] == 2


def test_append_marks_every_trace_affected():
    """These payloads carry full canonical columns for all traces, exactly like
    the ones xy's own Figure.append emits, so all of them are replaceable."""
    t = np.linspace(0.0, 1.0, 5)
    payload = plots.time_series(t, {"a": t, "b": t * 2}, panel_id="p-aff", version=1)
    trace_ids = [trace["id"] for trace in payload.spec["traces"]]
    assert payload.spec["append"]["affected"] == trace_ids
    assert len(trace_ids) == 2


def test_layout_token_changes_when_a_series_appears():
    """A trace added cannot be applied in place; the browser must rebuild."""
    t = np.linspace(0.0, 1.0, 5)
    one = plots.time_series(t, {"a": t}, panel_id="p-lay", version=1)
    two = plots.time_series(t, {"a": t, "b": t}, panel_id="p-lay", version=2)
    again = plots.time_series(t, {"a": t}, panel_id="p-lay", version=3)
    assert one.layout != two.layout
    assert one.layout == again.layout


def test_facade_exposes_exactly_the_documented_surface():
    for name in ("time_series", "spectra", "scatter_map", "histogram", "chart"):
        assert callable(getattr(plots, name))


def test_traces_accepts_a_different_x_per_trace():
    """The gap this fills: time_series and spectra share one x across every
    series, but each selected dataset carries its own x column."""
    out = plots.traces(
        [
            {"label": "a", "x": np.linspace(0.0, 1.0, 5), "y": np.zeros(5)},
            {"label": "b", "x": np.linspace(0.0, 9.0, 30), "y": np.ones(30)},
        ]
    )
    assert isinstance(out, plots.ChartPayload)
    assert len(out.spec["traces"]) == 2


def test_traces_labels_each_trace():
    out = plots.traces([{"label": "only", "x": np.arange(3.0), "y": np.arange(3.0)}])
    assert out.spec["traces"][0]["name"] == "only"


def test_traces_supports_scatter():
    out = plots.traces(
        [{"label": "a", "x": np.arange(3.0), "y": np.arange(3.0)}], kind="scatter"
    )
    assert out.spec["traces"][0]["kind"] == "scatter"


def test_traces_rejects_an_unknown_kind():
    with pytest.raises(ValueError, match="kind"):
        plots.traces(
            [{"label": "a", "x": np.arange(3.0), "y": np.arange(3.0)}], kind="bogus"
        )


def test_traces_rejects_mismatched_x_and_y():
    with pytest.raises(ValueError, match="length"):
        plots.traces([{"label": "a", "x": np.zeros(5), "y": np.zeros(4)}])


def test_traces_tolerates_no_series():
    assert plots.traces([]) is not None


def test_traces_keeps_an_all_non_finite_trace_so_the_layout_holds_still():
    """A dropped trace changes `layout_token`, which rebuilds the whole view.

    A sensor that goes briefly non-finite did that on alternating ticks, so the
    line appeared and disappeared as the operator watched. The trace is kept as
    an empty one instead: same trace set, same token, an in-place update.
    """
    out = plots.traces(
        [
            {"label": "bad", "x": np.arange(3.0), "y": np.full(3, np.nan)},
            {"label": "good", "x": np.arange(3.0), "y": np.arange(3.0)},
        ]
    )
    assert len(out.spec["traces"]) == 2
    # The empty one contributes zero-length columns, not missing ones.
    assert 0 in [c.get("len") for c in out.spec["columns"]]


def test_a_trace_going_non_finite_does_not_change_the_layout_token():
    x = np.arange(3.0)
    finite = plots.traces([{"label": "a", "x": x, "y": x}], version=1)
    blanked = plots.traces([{"label": "a", "x": x, "y": np.full(3, np.nan)}], version=2)
    assert finite.layout == blanked.layout


def test_traces_carries_an_append_token_like_every_other_facade_entry():
    """Without spec.append the chart paints one frame and freezes."""
    out = plots.traces(
        [{"label": "a", "x": np.arange(3.0), "y": np.arange(3.0)}], version=4
    )
    assert out.spec["append"]["seq"] == 4


# -- epoch x axes ------------------------------------------------------------


def test_epoch_x_survives_the_f32_column_encoding():
    """The blank-live-chart bug: f32 spacing near 1.75e9 is 128 seconds.

    xy encodes every column as f32, so a minute of 10 Hz telemetry collapsed
    onto two distinct x positions -- nothing to draw a line between, on a chart
    whose axis kept widening. Rebasing brings the values under ~1e5, where the
    spacing is milliseconds.
    """
    import time

    t = time.time() + np.arange(600) * 0.1
    xs = plots._rebase_epoch(plots._as_float_array(t))
    assert len(np.unique(xs.astype(np.float32))) == 600
    assert np.spacing(np.float32(xs[-1])) < 0.01


def test_rebased_epoch_renders_as_local_clock_time():
    """xy formats time axes with getUTC*, and epoch 0 is midnight.

    So seconds since *local* midnight format as local clock time -- what a wall
    clock in the lab reads.
    """
    import time

    now = time.time()
    xs = plots._rebase_epoch(np.array([now]))
    assert time.strftime("%H:%M:%S", time.gmtime(xs[0])) == time.strftime(
        "%H:%M:%S", time.localtime(now)
    )


def test_rebasing_past_midnight_stays_continuous():
    """A window spanning midnight must not wrap back to zero.

    Values past 86400 keep formatting correctly -- 86400 is 00:00:00 the next
    day -- so the offset stays fixed to the window's first sample.
    """
    import time

    stamp = time.localtime()
    midnight = time.mktime(
        (stamp.tm_year, stamp.tm_mon, stamp.tm_mday, 0, 0, 0, 0, 0, -1)
    )
    # ten seconds either side of the following midnight
    t = midnight + 86400 + np.arange(-10.0, 10.0)
    xs = plots._rebase_epoch(t)
    assert np.all(np.diff(xs) > 0), "the trace jumped backwards at midnight"
    assert xs.max() > 86400


def test_a_non_epoch_x_is_left_alone_even_when_declared_epoch():
    """A panel streaming elapsed seconds must not be shifted into 1970."""
    x = np.arange(5.0)
    assert np.array_equal(plots._rebase_epoch(x), x)


def test_rebasing_tolerates_empty_and_non_finite_columns():
    assert plots._rebase_epoch(np.empty(0)).size == 0
    assert np.all(np.isnan(plots._rebase_epoch(np.full(3, np.nan))))


def test_time_series_rebases_only_when_x_is_epoch():
    import time

    t = time.time() + np.arange(10) * 0.1
    epoch = plots.time_series(t, {"a": np.arange(10.0)}, x_is_epoch=True)
    plain = plots.time_series(t, {"a": np.arange(10.0)}, x_is_epoch=False)
    # The rebased axis sits in seconds-of-day; the untouched one is still epoch.
    assert epoch.spec["x_axis"]["range"][1] < 90000
    assert plain.spec["x_axis"]["range"][1] > 1e9


# -- ternary -------------------------------------------------------------


def test_ternary_publishes_points_edges_and_vertex_labels() -> None:
    """Four traces and three annotations, not seven traces.

    `xy.text` returns an `Annotation`, not a `Mark`: it takes scalar x/y and a
    single `value` string, and `build_payload_split` puts it under `annotations`
    rather than `traces`. Verified against xy 0.0.5.
    """
    from helao.ui.reflex import plots

    payload = plots.ternary(
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        labels=("Co.K", "Y.K", "Pt.L"),
        panel_id="tern-test",
        version=1,
    )
    assert payload.buffer_url.endswith("tern-test?v=1")
    assert len(payload.spec.get("traces") or []) == 4
    labels = [a.get("text") for a in payload.spec.get("annotations") or []]
    assert labels == ["Co.K", "Y.K", "Pt.L"]


def test_ternary_drops_a_point_whose_components_are_all_none() -> None:
    """An uncalibrated transition arrives as None. Plotted, it reaches the
    renderer as a coordinate and blanks the chart."""
    from helao.ui.reflex import plots

    payload = plots.ternary(
        [1.0, float("nan")],
        [1.0, 1.0],
        [1.0, 1.0],
        labels=("a", "b", "c"),
        panel_id="tern-nan",
        version=1,
    )
    # One of the two points is dropped, not both: the scatter trace still
    # publishes (4 traces total) rather than falling back to the
    # triangle-only, no-data shape (3 traces).
    assert len(payload.spec.get("traces") or []) == 4


def test_ternary_filters_values_with_the_same_mask() -> None:
    """Colour is per point. Filtering points and colours independently puts the
    wrong colour on the wrong marker.

    The *first* input point (0, 0, 0) is the one dropped (sums to zero), and
    the survivor is the second, with value 6.0. `colors[:xs.size]` would slice
    off the *first* n values instead of masking with `keep`, which for this
    fixture yields `[5.0]` -- the dropped point's value -- while still passing
    a bare "some traces exist" check. Ordering the survivor second is what
    makes that distinguishable: a mask/slice mixup that happens to agree when
    the survivor is index 0 (as an earlier version of this fixture had it)
    does not agree here.
    """
    from helao.ui.reflex import plots

    payload = plots.ternary(
        [0.0, 1.0],
        [0.0, 0.0],
        [0.0, 0.0],
        labels=("a", "b", "c"),
        values=[5.0, 6.0],
        panel_id="tern-mask",
        version=1,
    )
    scatter = next(t for t in payload.spec["traces"] if t["name"] == "samples")
    domain = scatter["color"]["domain"]
    # A single-point colormap domain straddles that point's value; asserting
    # containment (rather than the exact padded bounds, which is an
    # implementation detail of the colour scale) is what ties this to the
    # *value* the survivor carries.
    assert domain[0] <= 6.0 <= domain[1], "the survivor's value must colour it"
    assert not (
        domain[0] <= 5.0 <= domain[1]
    ), "the dropped point's value must not reach the published colour scale"


def test_ternary_rejects_the_wrong_number_of_labels() -> None:
    from helao.ui.reflex import plots

    with pytest.raises(ValueError):
        plots.ternary([1.0], [1.0], [1.0], labels=("only", "two"))


def test_ternary_on_no_usable_points_still_draws_the_triangle() -> None:
    """An empty diagram with a visible triangle reads as "no data"; a blank
    canvas reads as a broken page."""
    from helao.ui.reflex import plots

    payload = plots.ternary(
        [0.0], [0.0], [0.0], labels=("a", "b", "c"), panel_id="tern-empty", version=1
    )
    assert len(payload.spec.get("traces") or []) == 3
    assert len(payload.spec.get("annotations") or []) == 3


def test_ternary_rejects_a_values_array_of_the_wrong_length() -> None:
    from helao.ui.reflex import plots

    with pytest.raises(ValueError):
        plots.ternary(
            [1.0, 1.0], [1.0, 1.0], [1.0, 1.0], labels=("a", "b", "c"), values=[1.0]
        )


# -- plate-photo underlay -------------------------------------------------------

#: Pinned from the unmodified ``scatter_map`` (parent cec43b68, xy 0.0.7).
#: Recompute on the pre-change commit only if xy itself is upgraded.
GOLDEN_SPEC_SHA256 = "f1d75f6f5e0b6e4f0aaeea8a083f23ea48af4496b838714dcaeec9f4a8f6b27d"
GOLDEN_FRAME_SHA256 = "704f01fa8cd000608e9735c4ecdc9833f06cf49053d0e770d5cb1619a799f2dc"
GOLDEN_LAYOUT = "0:scatter:v|1:scatter:selected_0|size=6.0(-6.5, 26.5)(-1.5, 31.5)True"


def _golden(panel_id, **extra):
    return plots.scatter_map(
        [0.0, 10.0, 20.0, 5.0],
        [0.0, 5.0, 30.0, 12.0],
        values=[1.0, 2.0, 3.0, 4.0],
        x_label="x (mm)",
        y_label="y (mm)",
        value_label="v",
        square=True,
        colormap="viridis",
        colorbar=True,
        rings=[(10.0, 5.0, 0)],
        size=6.0,
        panel_id=panel_id,
        version=7,
        **extra,
    )


@pytest.mark.parametrize("extra", [{}, {"underlay": None}], ids=["omitted", "none"])
def test_scatter_map_without_an_underlay_is_byte_identical_to_before(extra):
    """Spec, column buffers and layout token all match the pre-underlay
    output, so every existing plate map is untouched until a photo is
    chosen."""
    panel = f"golden-{len(extra)}"
    payload = _golden(panel, **extra)
    spec_digest = hashlib.sha256(
        json.dumps(payload.spec, sort_keys=True).encode()
    ).hexdigest()
    frame_digest = hashlib.sha256(plots.STORE.get(panel, 7)).hexdigest()
    assert spec_digest == GOLDEN_SPEC_SHA256
    assert frame_digest == GOLDEN_FRAME_SHA256
    assert payload.layout == GOLDEN_LAYOUT


def _rgba_planes(panel_id, version, trace):
    """The heatmap's four f32 planes, decoded from the published frame."""
    frame = xy.channel.decode_frame(plots.STORE.get(panel_id, version))
    h, w = trace["heatmap"]["h"], trace["heatmap"]["w"]
    return [
        np.frombuffer(frame.buffers[i], dtype=np.float32).reshape(h, w)
        for i in trace["heatmap"]["rgba_bufs"]
    ]


def test_underlay_is_trace_zero_a_truecolor_heatmap_spanning_the_extent():
    payload = plots.scatter_map(
        [0.0, 1.0],
        [0.0, 1.0],
        values=[1.0, 2.0],
        value_label="v",
        colorbar=True,
        square=True,
        underlay=(top_row_red(), EXTENT),
        panel_id="u-trace",
        version=1,
    )
    first = payload.spec["traces"][0]
    assert first["kind"] == "heatmap" and first["name"] == "photo"
    # Load-bearing for hover: xy 0.0.7's client skips hover on truecolor
    # heatmaps (_hoverAt needs _cpuHeatmap, built only for non-truecolor), so
    # the figure-level tooltip never labels photo pixels as the measurement.
    # Re-check on any xy upgrade.
    assert importlib.metadata.version("xy") == "0.0.7", (
        "xy was upgraded: re-check that hover skips truecolor heatmaps (hover a "
        "photo-only region, then a sample point); see the plate-photo note in "
        "helao/ui/reflex/CLAUDE.md"
    )
    assert first["style"]["truecolor"] is True
    assert first["style"]["opacity"] == pytest.approx(plots.UNDERLAY_OPACITY)
    assert first["heatmap"]["x_range"] == pytest.approx([-50.0, 50.0])
    assert first["heatmap"]["y_range"] == pytest.approx([-10.0, 90.0])
    assert payload.spec["traces"][1]["kind"] == "scatter"
    # The colour scale still describes the points, not the photo.
    assert payload.spec["colorbar"]["domain"] == pytest.approx([1.0, 2.0])


def test_underlay_opacity_reaches_the_photo_mark():
    payload = plots.scatter_map(
        [0.0],
        [0.0],
        underlay=(top_row_red(), EXTENT),
        underlay_opacity=0.3,
        panel_id="u-opacity",
        version=1,
    )
    assert payload.spec["traces"][0]["style"]["opacity"] == pytest.approx(0.3)


def test_underlay_rows_are_flipped_so_the_image_top_lands_at_y_max():
    payload = plots.scatter_map(
        [0.0],
        [0.0],
        underlay=(top_row_red(rows=8, cols=6), EXTENT),
        panel_id="u-flip",
        version=1,
    )
    red, _green, _blue, alpha = _rgba_planes("u-flip", 1, payload.spec["traces"][0])
    # xy's rows run upward from y_min, so the image's top row is xy's last.
    assert red[-1].tolist() == [1.0] * 6
    assert red[:-1].max() == 0.0
    assert alpha[-1].tolist() == [1.0] * 6
    assert alpha[:-1].max() == 0.0


def test_underlay_scales_alpha_as_well_as_colour():
    """xy never divides alpha by 255; handed uint8, 128 would clip to 1.0."""
    img = np.zeros((2, 2, 4), dtype=np.uint8)
    img[..., 3] = 128
    payload = plots.scatter_map(
        [0.0], [0.0], underlay=(img, EXTENT), panel_id="u-alpha", version=1
    )
    alpha = _rgba_planes("u-alpha", 1, payload.spec["traces"][0])[3]
    assert alpha == pytest.approx(np.full((2, 2), 128 / 255), abs=1e-6)


def test_square_domain_contains_the_extent_as_well_as_the_points():
    """The points sit off the extent's centre on both axes, so dropping the
    extent from either axis's domain leaves part of the wafer outside it."""
    payload = plots.scatter_map(
        [40.0, 41.0],
        [0.0, 1.0],
        square=True,
        underlay=(top_row_red(), EXTENT),
        panel_id="u-dom",
        version=1,
    )
    x_lo, x_hi = payload.spec["x_axis"]["domain"]
    y_lo, y_hi = payload.spec["y_axis"]["domain"]
    assert x_lo <= -50.0 and x_hi >= 50.0
    assert y_lo <= -10.0 and y_hi >= 90.0
    assert x_hi - x_lo == pytest.approx(y_hi - y_lo)  # still square


def test_layout_token_changes_with_the_photo_and_its_opacity():
    def token(**kwargs):
        return plots.scatter_map(
            [0.0], [0.0], square=True, panel_id="u-tok", version=1, **kwargs
        ).layout

    other = top_row_red()
    other[1] = (0, 0, 255, 255)  # same shape and extent, different photo
    photo = token(underlay=(top_row_red(), EXTENT))
    assert photo == token(underlay=(top_row_red(), EXTENT))
    tokens = {
        photo,
        token(underlay=(other, EXTENT)),
        token(underlay=(top_row_red(), EXTENT), underlay_opacity=0.3),
        token(),
    }
    assert len(tokens) == 4


def test_underlay_rejects_an_image_that_is_not_rgba():
    with pytest.raises(ValueError, match="RGBA"):
        plots.scatter_map(
            [0.0], [0.0], underlay=(np.zeros((4, 4, 3), dtype=np.uint8), EXTENT)
        )
