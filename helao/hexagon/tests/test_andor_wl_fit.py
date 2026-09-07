"""The arc-lamp wavelength-solution pipeline, end to end on synthetic frames.

The load-bearing test here is the round trip: build a frame from a KNOWN
wavelength axis using the real NIST krypton lines, hand the pipeline two
anchors, and check it recovers the axis it was built from. Everything else in
this file exists to pin one failure mode of that pipeline in isolation.

No hardware and no vendor SDK: the whole module operates on an array of
counts.
"""

import numpy as np
import pytest

from helao.deploy.hte.drivers.spec.andor import wl_calibration as wlc
from helao.deploy.hte.drivers.spec.andor import wl_fit
from helao.deploy.hte.drivers.spec.andor.kr_lines import KR_LINES_AIR_NM

N_PIXELS = 2560

#: A plausible grating solution for this detector: ~430-890 nm across 2560
#: columns, with real curvature so a linear or quadratic fit cannot pass by
#: accident. Chebyshev coefficients over the full pixel domain.
TRUE_COEFFS = [660.0, 232.0, 6.0, 1.2, 0.4]
DOMAIN = [0.0, float(N_PIXELS - 1)]


def true_axis():
    return np.polynomial.chebyshev.Chebyshev(TRUE_COEFFS, domain=DOMAIN)(
        np.arange(N_PIXELS, dtype=float)
    )


def pixel_of(wavelength_nm):
    """Invert the true axis: which pixel a given wavelength lands on."""
    axis = true_axis()
    return float(np.interp(wavelength_nm, axis, np.arange(N_PIXELS, dtype=float)))


def synth_frame(
    *, min_intensity=100, sigma_px=2.0, noise=0.0, saturate_at=None, seed=0
):
    """A krypton lamp frame built from the true axis and the real line list."""
    axis = true_axis()
    lo, hi = float(axis[0]), float(axis[-1])
    counts = np.full(N_PIXELS, 100.0)
    pixels = np.arange(N_PIXELS, dtype=float)
    used = []
    for wl, intensity, _species in KR_LINES_AIR_NM:
        if not (lo + 1.0 <= wl <= hi - 1.0) or intensity < min_intensity:
            continue
        centre = pixel_of(wl)
        counts += intensity * np.exp(-0.5 * ((pixels - centre) / sigma_px) ** 2)
        used.append((wl, centre))
    if noise:
        counts = counts + np.random.default_rng(seed).normal(0.0, noise, N_PIXELS)
    if saturate_at is not None:
        counts = np.minimum(counts, saturate_at)
    return counts, used


def anchors_from(counts, used, n=8):
    """Anchors an operator could actually pick off THIS frame.

    Chosen from the lines the pipeline detects, not from the injected truth:
    under noise or saturation some injected lines are simply not visible, and
    an operator cannot anchor on a line they cannot see. Each detected line is
    labelled with the nearest true wavelength, and only well-separated
    interior lines are eligible -- a blend centroids between its two
    components, which is the one thing an anchor must not do.

    Both halves are then rounded, to a whole pixel and two decimals, because
    that is the precision of reading a value off a plot. Absorbing that is
    what the snapping in ``fit_wavelength`` is for.
    """
    truth_px = np.array([px for _wl, px in used])
    truth_wl = np.array([wl for wl, _px in used])
    anchorable_wl = {w for w, _i, _s in wl_fit.usable_catalogue()}
    centroids = wl_fit.centroid_peaks(counts, wl_fit.detect_peaks(counts))
    eligible = []
    for c in centroids:
        if not (60 < c.pixel < N_PIXELS - 60):
            continue
        j = int(np.argmin(np.abs(truth_px - c.pixel)))
        if abs(truth_px[j] - c.pixel) > 1.0:
            continue  # a blend: no single true line owns this peak
        others = np.delete(truth_px, j)
        if np.min(np.abs(others - truth_px[j])) < 14:
            continue  # a true neighbour close enough to pull the centroid
        if float(truth_wl[j]) not in anchorable_wl:
            continue  # dropped from the catalogue as a blend; unanchorable
        eligible.append((float(truth_wl[j]), c.pixel))
    if len(eligible) < n:
        raise AssertionError(f"only {len(eligible)} anchorable lines in this frame")
    idx = np.linspace(0, len(eligible) - 1, n).round().astype(int)
    return [[round(eligible[i][1]), round(eligible[i][0], 2)] for i in idx]


# --- the round trip ----------------------------------------------------------


def test_two_anchors_recover_the_axis_they_were_built_from():
    counts, used = synth_frame()
    calib = wl_fit.fit_wavelength(counts, anchors_from(counts, used), degree=4)

    assert calib.model == wlc.MODEL_CHEB
    assert calib.n_pixels == N_PIXELS
    assert calib.medium == "air"
    assert calib.n_lines >= 20, f"only identified {calib.n_lines} lines"
    # Sub-picometre against a noiseless synthetic frame. The bound is loose
    # enough not to be brittle and tight enough that a mis-identified line,
    # which displaces a point by a whole line spacing, cannot pass.
    assert calib.fit_rms_nm < 0.02, calib.fit_rms_nm
    assert calib.max_residual_nm < 0.05, calib.max_residual_nm

    recovered = wlc.evaluate(calib)
    assert np.max(np.abs(recovered - true_axis())) < 0.05


def test_the_recovered_axis_is_monotonic():
    counts, used = synth_frame()
    calib = wl_fit.fit_wavelength(counts, anchors_from(counts, used), degree=4)
    assert wlc.is_monotonic(wlc.evaluate(calib))


def test_it_survives_realistic_noise():
    counts, used = synth_frame(noise=30.0)
    calib = wl_fit.fit_wavelength(counts, anchors_from(counts, used), degree=4)
    assert calib.n_lines >= 15
    # Measured 0.063 nm at this noise level. The bound sits above that and an
    # order of magnitude below what one mis-identified line would produce.
    assert calib.fit_rms_nm < 0.1, calib.fit_rms_nm


def test_the_fit_round_trips_through_disk(tmp_path):
    """A Chebyshev record must evaluate identically after save/load."""
    counts, used = synth_frame()
    calib = wl_fit.fit_wavelength(counts, anchors_from(counts, used), degree=4)
    path = tmp_path / "calib.json"
    wlc.save(calib, path)
    reloaded = wlc.load(path)
    assert reloaded.model == wlc.MODEL_CHEB
    assert reloaded.domain == DOMAIN
    assert np.allclose(wlc.evaluate(reloaded), wlc.evaluate(calib))


# --- the pieces --------------------------------------------------------------


def test_peaks_are_found_against_a_sloping_background():
    """Prominence, not height: a ramp must not swamp the dim end."""
    counts, used = synth_frame()
    ramp = np.linspace(0.0, 4000.0, N_PIXELS)
    found_flat = wl_fit.detect_peaks(counts)
    found_ramped = wl_fit.detect_peaks(counts + ramp)
    # A height threshold would lose the low-wavelength lines under the ramp.
    assert len(found_ramped) >= 0.9 * len(found_flat), (
        len(found_flat),
        len(found_ramped),
    )


def test_centroids_are_sub_pixel():
    """The integer index is up to half a pixel wrong; the Gaussian is not."""
    counts, used = synth_frame()
    found = wl_fit.detect_peaks(counts)
    centroids = wl_fit.centroid_peaks(counts, found)
    truth = np.array(sorted(px for _wl, px in used))
    isolated = [
        t
        for i, t in enumerate(truth)
        if (i == 0 or t - truth[i - 1] > 14)
        and (i == len(truth) - 1 or truth[i + 1] - t > 14)
    ]
    got = np.array(sorted(c.pixel for c in centroids))
    errors = [min(abs(g - t) for g in got) for t in isolated]
    assert errors, "no isolated line to judge"
    # Measured worst case 0.38 px on isolated lines. Half a pixel is the error
    # the Gaussian exists to remove, so the bound has to sit below it.
    assert max(errors) < 0.5, max(errors)
    # And they are genuinely off-grid, so the refinement really ran.
    assert any(abs(g - round(g)) > 0.05 for g in got)


def test_saturated_lines_are_excluded_and_counted():
    counts, used = synth_frame(saturate_at=400.0)
    calib = wl_fit.fit_wavelength(
        counts, anchors_from(counts, used), degree=4, saturation=400.0
    )
    assert calib.n_saturated > 0
    assert calib.fit_rms_nm < 0.1


def test_blended_catalogue_lines_are_dropped():
    """431.781/431.855 nm are 0.074 nm apart and cannot be resolved."""
    cat = wl_fit.usable_catalogue(min_separation_nm=0.25)
    wavelengths = [w for w, _i, _s in cat]
    assert 431.781 not in wavelengths
    assert 431.85513 not in wavelengths
    # An isolated strong line must survive the same filter.
    assert 473.9002 in wavelengths


def test_the_catalogue_filter_judges_against_unfiltered_neighbours():
    """Removing the faint half of a blend must not leave the bright half."""
    lines = [(500.0, 1000, "Kr I"), (500.05, 10, "Kr I"), (600.0, 500, "Kr I")]
    kept = [w for w, _i, _s in wl_fit.usable_catalogue(lines, min_separation_nm=0.25)]
    assert kept == [600.0]


# --- refusals ----------------------------------------------------------------


def test_an_under_determined_seed_is_refused():
    counts, used = synth_frame()
    with pytest.raises(wl_fit.CalibrationFitError, match="needs at least 8 anchors"):
        wl_fit.fit_wavelength(counts, anchors_from(counts, used)[:4], degree=4)


def test_an_anchor_matching_no_catalogue_line_is_refused():
    counts, used = synth_frame()
    anchors = anchors_from(counts, used)
    anchors[0][1] = 123.456  # nowhere near a krypton line
    with pytest.raises(wl_fit.CalibrationFitError, match="matches no catalogue line"):
        wl_fit.fit_wavelength(counts, anchors, degree=4)


def test_an_anchor_pixel_with_no_detected_line_is_refused():
    counts, used = synth_frame()
    anchors = anchors_from(counts, used)
    gaps = np.diff(sorted(px for _wl, px in used))
    empty = int(sorted(px for _wl, px in used)[int(np.argmax(gaps))] + gaps.max() / 2)
    anchors[0][0] = empty  # the widest gap between lines: nothing to snap to
    with pytest.raises(wl_fit.CalibrationFitError, match="no detected line"):
        wl_fit.fit_wavelength(counts, anchors, degree=4)


def test_a_featureless_frame_is_refused():
    with pytest.raises(wl_fit.CalibrationFitError):
        wl_fit.fit_wavelength(
            np.full(N_PIXELS, 100.0), [[i * 200, 450.0 + i * 50] for i in range(8)]
        )


def test_too_few_lines_for_the_degree_is_refused():
    """A frame with only a handful of lines cannot support a degree-4 fit."""
    full, used = synth_frame()
    anchors = anchors_from(full, used)
    sparse, _ = synth_frame(min_intensity=990)  # only the four brightest
    with pytest.raises(wl_fit.CalibrationFitError, match="needs at least"):
        wl_fit.fit_wavelength(sparse, anchors, degree=4)


# --- rejection ---------------------------------------------------------------


def test_a_cosmic_ray_does_not_bend_the_solution():
    """An unrelated bright spike must be clipped, not fitted."""
    counts, used = synth_frame()
    clean = wl_fit.fit_wavelength(counts, anchors_from(counts, used), degree=4)
    spiked = counts.copy()
    spiked[1234] += 20000.0
    dirty = wl_fit.fit_wavelength(spiked, anchors_from(counts, used), degree=4)
    assert dirty.fit_rms_nm < 0.05, dirty.fit_rms_nm
    axis_shift = np.max(np.abs(wlc.evaluate(dirty) - wlc.evaluate(clean)))
    assert axis_shift < 0.05, axis_shift


# --- the direct route: fit_from_pairs ----------------------------------------
#
# No detection, no catalogue, no matching. The caller has already decided
# which channel is which wavelength. It cannot check them -- with no
# independent evidence a mislabelled pair fits as faithfully as a correct one
# -- which is exactly why the anchored route above exists beside it.


def test_pairs_recover_a_quadratic_axis_exactly():
    px = [100.0, 800.0, 1500.0, 2200.0, 2500.0]
    truth = np.polynomial.chebyshev.Chebyshev([650.0, 230.0, 5.0], domain=DOMAIN)
    pairs = [(p, float(truth(p))) for p in px]
    calib = wl_fit.fit_from_pairs(pairs, N_PIXELS, degree=2)

    assert calib.model == wlc.MODEL_CHEB
    assert calib.n_lines == 5
    assert calib.fit_rms_nm < 1e-9
    assert np.max(np.abs(wlc.evaluate(calib) - truth(np.arange(N_PIXELS)))) < 1e-9


def test_three_pairs_at_degree_two_interpolate_and_say_so():
    """rms 0 on exactly degree+1 points is arithmetic, not accuracy."""
    calib = wl_fit.fit_from_pairs(
        [(0.0, 430.0), (1280.0, 660.0), (2559.0, 900.0)], N_PIXELS, degree=2
    )
    assert calib.n_lines == 3
    assert calib.fit_rms_nm == pytest.approx(0.0, abs=1e-9)


def test_too_few_pairs_for_the_degree_is_refused():
    with pytest.raises(wl_fit.CalibrationFitError, match="at least 3 pairs"):
        wl_fit.fit_from_pairs([(0.0, 430.0), (2559.0, 900.0)], N_PIXELS, degree=2)


def test_a_repeated_channel_is_refused():
    """Two wavelengths at one channel is a contradiction, not a measurement."""
    with pytest.raises(wl_fit.CalibrationFitError, match="same channel"):
        wl_fit.fit_from_pairs(
            [(100.0, 430.0), (100.0, 500.0), (2000.0, 880.0)], N_PIXELS, degree=2
        )


def test_pairs_record_the_medium_and_round_trip(tmp_path):
    calib = wl_fit.fit_from_pairs(
        [(0.0, 430.0), (900.0, 600.0), (1800.0, 780.0), (2559.0, 900.0)],
        N_PIXELS,
        degree=2,
    )
    assert calib.medium == "air"
    assert calib.lamp == "manual"
    path = tmp_path / "c.json"
    wlc.save(calib, path)
    assert np.allclose(wlc.evaluate(wlc.load(path)), wlc.evaluate(calib))
