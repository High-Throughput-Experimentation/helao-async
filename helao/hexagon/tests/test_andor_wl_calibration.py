"""Pure wavelength-calibration numerics and persistence.

No vendor SDK and no HELAO server are involved, so this whole file runs on
Linux with nothing installed. That is the point of keeping the numerics in
their own module: the part most likely to need iteration is the part that
needs no hardware to iterate on.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from helao.deploy.hte.drivers.spec.andor import wl_calibration as wlc


def _synthetic_lamp(coeffs, n_pixels, line_pixels, width=2.0):
    """A spectrum with Gaussian peaks at `line_pixels`, flat elsewhere."""
    pixels = np.arange(n_pixels, dtype=float)
    counts = np.full(n_pixels, 100.0)
    for p in line_pixels:
        counts += 5000.0 * np.exp(-0.5 * ((pixels - p) / width) ** 2)
    return counts


TRUE_COEFFS = [400.0, 0.2, 1e-6, 1e-10]
N_PIXELS = 2560
LINE_PIXELS = [200, 700, 1300, 1900, 2400]
OFF_GRID_PIXELS = [200.37, 700.62, 1300.15, 1900.88, 2400.41]


def _true_nm(pixel):
    return sum(c * pixel**i for i, c in enumerate(TRUE_COEFFS))


def test_evaluate_reproduces_the_polynomial():
    calib = wlc.WavelengthCalibration(
        model=wlc.MODEL_POLY,
        coeffs=TRUE_COEFFS,
        n_pixels=8,
        fit_rms_nm=0.0,
        n_lines=0,
        lamp="none",
        created="2026-09-04T00:00:00Z",
        source_action_uuid=None,
    )
    wl = wlc.evaluate(calib)
    assert wl.shape == (8,)
    assert wl[0] == pytest.approx(_true_nm(0))
    assert wl[7] == pytest.approx(_true_nm(7))


def test_fit_recovers_a_known_polynomial():
    counts = _synthetic_lamp(TRUE_COEFFS, N_PIXELS, LINE_PIXELS)
    lines = [_true_nm(p) for p in LINE_PIXELS]
    calib = wlc.fit_wavelength(counts, lines, degree=3, lamp="synthetic")

    assert calib.model == wlc.MODEL_POLY
    assert calib.n_pixels == N_PIXELS
    assert calib.n_lines == len(LINE_PIXELS)
    assert calib.lamp == "synthetic"
    assert calib.fit_rms_nm < 0.5

    wl = wlc.evaluate(calib)
    for p in LINE_PIXELS:
        assert wl[p] == pytest.approx(_true_nm(p), abs=1.0)


def test_fit_refuses_when_peaks_and_lines_disagree_in_count():
    counts = _synthetic_lamp(TRUE_COEFFS, N_PIXELS, LINE_PIXELS)
    with pytest.raises(ValueError, match="line"):
        wlc.fit_wavelength(counts, [400.0, 500.0], degree=3)


def test_fit_refuses_a_degree_it_cannot_support():
    counts = _synthetic_lamp(TRUE_COEFFS, N_PIXELS, LINE_PIXELS)
    lines = [_true_nm(p) for p in LINE_PIXELS]
    with pytest.raises(ValueError, match="degree"):
        wlc.fit_wavelength(counts, lines, degree=9)


def test_round_trip_through_disk(tmp_path):
    calib = wlc.WavelengthCalibration(
        model=wlc.MODEL_POLY,
        coeffs=TRUE_COEFFS,
        n_pixels=N_PIXELS,
        fit_rms_nm=0.01,
        n_lines=5,
        lamp="Hg-Ar",
        created="2026-09-04T00:00:00Z",
        source_action_uuid="abc-123",
    )
    path = tmp_path / "calib.json"
    wlc.save(calib, path)
    assert wlc.load(path) == calib


def test_load_refuses_an_unknown_model(tmp_path):
    """A record this build cannot evaluate must not be silently mis-read."""
    path = tmp_path / "calib.json"
    path.write_text(
        json.dumps(
            {
                "model": "chebyshev",
                "coeffs": [1.0],
                "n_pixels": 4,
                "fit_rms_nm": 0.0,
                "n_lines": 0,
                "lamp": "x",
                "created": "2026-09-04T00:00:00Z",
                "source_action_uuid": None,
            }
        )
    )
    with pytest.raises(wlc.UnknownCalibrationModel, match="chebyshev"):
        wlc.load(path)


def test_save_writes_readable_json(tmp_path):
    """The record is meant to be diagnosed by eye in a station's STATES dir."""
    calib = wlc.WavelengthCalibration(
        model=wlc.MODEL_POLY,
        coeffs=[1.0, 2.0],
        n_pixels=2,
        fit_rms_nm=0.5,
        n_lines=2,
        lamp="Hg-Ar",
        created="2026-09-04T00:00:00Z",
        source_action_uuid=None,
    )
    path = tmp_path / "calib.json"
    wlc.save(calib, path)
    loaded = json.loads(path.read_text())
    assert loaded["lamp"] == "Hg-Ar"
    assert loaded["fit_rms_nm"] == 0.5
    assert "\n" in path.read_text(), "expected indented JSON, not one line"


def test_calibration_path_follows_the_station_convention():
    p = wlc.calibration_path("/root/STATES", "hte-eche-11", "ANDOR")
    assert p == Path("/root/STATES/hte-eche-11_ANDOR_andor_wl_calib.json")


def test_module_imports_no_vendor_or_server_package():
    """Keeping this module pure is what lets it be iterated on Linux."""
    src = Path(wlc.__file__).read_text()
    for banned in ("pyAndor", "helao.core", "helao.helpers", "fastapi"):
        assert banned not in src, f"{banned} must not appear in wl_calibration.py"


def test_sub_pixel_refinement_actually_runs():
    """Lines off the pixel grid: raw integer peaks are not good enough.

    Every other test puts lines at exact integer pixels with symmetric
    peaks, so y0 == y2 and the parabolic offset is identically 0.0 --
    find_peaks could skip refinement entirely and pass. Here the true
    centres are up to 0.5 px off-grid, so an unrefined integer index
    carries a real wavelength error.
    """
    counts = _synthetic_lamp(TRUE_COEFFS, N_PIXELS, OFF_GRID_PIXELS)
    found = wlc.find_peaks(counts, len(OFF_GRID_PIXELS))
    assert len(found) == len(OFF_GRID_PIXELS)
    for got, want in zip(found, OFF_GRID_PIXELS):
        assert abs(got - want) < 0.15, f"{got} vs {want}: refinement is off"
    assert any(
        abs(got - round(got)) > 0.05 for got in found
    ), "every centroid landed on an integer -- refinement did not run"


def test_off_grid_lines_still_fit_tightly():
    """The residual must stay small when the lines are not on the grid.

    An unrefined peak finder rounds to the nearest pixel, up to 0.5 px of
    error, which at this dispersion is ~0.1 nm -- an order of magnitude
    above this bound.
    """
    lines = [_true_nm(p) for p in OFF_GRID_PIXELS]
    counts = _synthetic_lamp(TRUE_COEFFS, N_PIXELS, OFF_GRID_PIXELS)
    calib = wlc.fit_wavelength(counts, lines, degree=3, lamp="synthetic")
    assert calib.fit_rms_nm < 0.02, calib.fit_rms_nm


def test_lines_closer_than_the_separation_are_refused_not_guessed():
    """Two lines 3 px apart are inside find_peaks' 5 px exclusion.

    The safe outcome is that fit_wavelength cannot locate one peak per
    reference line and RAISES, rather than quietly pairing a peak with
    the wrong wavelength.
    """
    close = [200.0, 203.0, 700.0, 1300.0, 1900.0, 2400.0]
    counts = _synthetic_lamp(TRUE_COEFFS, N_PIXELS, close)
    lines = [_true_nm(p) for p in close]
    with pytest.raises(ValueError, match="peak"):
        wlc.fit_wavelength(counts, lines, degree=3)


def test_a_brighter_non_reference_feature_shows_up_as_a_bad_residual():
    """find_peaks has no outlier rejection: it takes the strongest maxima.

    A cosmic-ray spike brighter than the lamp lines displaces the weakest
    real line from the selection, so a peak is paired with the wrong
    reference wavelength. Nothing raises. What the operator has to catch
    it is fit_rms_nm, so pin that the residual actually blows up.
    """
    counts = _synthetic_lamp(TRUE_COEFFS, N_PIXELS, LINE_PIXELS)
    counts[1000] += 50000.0  # a spike well above every line
    lines = [_true_nm(p) for p in LINE_PIXELS]
    calib = wlc.fit_wavelength(counts, lines, degree=3)
    assert calib.fit_rms_nm > 1.0, (
        f"a mis-assigned peak produced rms {calib.fit_rms_nm}, which an "
        "operator would read as a good calibration"
    )


def test_is_monotonic_accepts_an_axis_that_only_increases():
    assert wlc.is_monotonic(np.linspace(300.0, 800.0, 2560))


def test_is_monotonic_accepts_an_axis_that_only_decreases():
    """A reversed detector read-out is a legitimate axis, just descending."""
    assert wlc.is_monotonic(np.linspace(800.0, 300.0, 2560))


def test_is_monotonic_refuses_an_axis_that_turns_back_on_itself():
    """Two pixels claiming the same wavelength is not a calibration."""
    axis = np.concatenate(
        [np.linspace(400.0, 500.0, 100), np.linspace(499.0, 600.0, 100)]
    )
    assert not wlc.is_monotonic(axis)


def test_is_monotonic_refuses_a_repeated_value():
    """Strict, not merely non-decreasing: a flat run is a degenerate axis."""
    assert not wlc.is_monotonic([400.0, 401.0, 401.0, 402.0])


def test_is_monotonic_refuses_a_nan():
    """A NaN makes both comparisons False, and that is the safe direction."""
    assert not wlc.is_monotonic([400.0, np.nan, 402.0])


def test_is_monotonic_tolerates_an_axis_too_short_to_violate_it():
    assert wlc.is_monotonic([])
    assert wlc.is_monotonic([400.0])


NON_MONOTONIC_LINE_PIXELS = [700, 1200, 1700, 2100, 2500]


def _turning_poly(pixel):
    """A cubic that dips before pixel 300 and rises monotonically after.

    Sampled at :data:`NON_MONOTONIC_LINE_PIXELS` it is strictly ascending, so
    the fit is exact and its residual is ~1e-13 -- it sails through the rms
    gate. Evaluated across the whole detector it turns over, which is the
    case ``is_monotonic`` exists to catch and rms cannot.
    """
    return 1e-9 * pixel**3 + 1.05e-6 * pixel**2 - 9e-4 * pixel + 400.0


def test_a_tight_fit_can_still_describe_a_non_monotonic_axis():
    """Why rms alone is not enough of a gate."""
    counts = _synthetic_lamp(TRUE_COEFFS, N_PIXELS, NON_MONOTONIC_LINE_PIXELS)
    lines = [_turning_poly(p) for p in NON_MONOTONIC_LINE_PIXELS]
    calib = wlc.fit_wavelength(counts, lines, degree=3)
    assert calib.fit_rms_nm < 0.5, "this fixture must clear the rms gate"
    assert not wlc.is_monotonic(wlc.evaluate(calib))


def test_save_moves_the_outgoing_calibration_to_a_prev_sibling(tmp_path):
    """An overwrite must be recoverable: it destroys a known-good record."""
    path = tmp_path / "calib.json"
    first = wlc.WavelengthCalibration(
        model=wlc.MODEL_POLY,
        coeffs=[400.0, 0.2],
        n_pixels=16,
        fit_rms_nm=0.01,
        n_lines=5,
        lamp="first",
        created="2026-09-04T00:00:00Z",
        source_action_uuid=None,
    )
    wlc.save(first, path)
    assert not path.with_name("calib.json.prev").exists(), "nothing to back up yet"

    second = wlc.WavelengthCalibration(
        model=wlc.MODEL_POLY,
        coeffs=[500.0, 0.3],
        n_pixels=16,
        fit_rms_nm=0.02,
        n_lines=5,
        lamp="second",
        created="2026-09-05T00:00:00Z",
        source_action_uuid=None,
    )
    wlc.save(second, path)

    assert wlc.load(path) == second
    assert wlc.load(path.with_name("calib.json.prev")) == first


def test_the_prev_backup_leaves_no_staging_file_behind(tmp_path):
    """The staging name follows the repo's `.<name>.tmp` convention.

    The syncer ships anything it finds in a record directory that is not a
    dotfile or a `.tmp`; a backup left half-written under any other name
    would be uploaded.
    """
    path = tmp_path / "calib.json"
    calib = wlc.WavelengthCalibration(
        model=wlc.MODEL_POLY,
        coeffs=[400.0, 0.2],
        n_pixels=16,
        fit_rms_nm=0.01,
        n_lines=5,
        lamp="x",
        created="2026-09-04T00:00:00Z",
        source_action_uuid=None,
    )
    wlc.save(calib, path)
    wlc.save(calib, path)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "calib.json",
        "calib.json.prev",
    ]


def test_fit_records_the_variant_that_asked_for_it():
    counts = _synthetic_lamp(TRUE_COEFFS, N_PIXELS, LINE_PIXELS)
    lines = [_true_nm(p) for p in LINE_PIXELS]
    calib = wlc.fit_wavelength(counts, lines, degree=3, wl_source="calibration")
    assert calib.wl_source == "calibration"


def test_load_defaults_an_absent_wl_source_to_unknown(tmp_path):
    """Records written before the field existed must keep loading.

    Refusing them would strand a station that calibrated legitimately last
    month; "unknown" is both true and exactly what a reader needs told.
    """
    path = tmp_path / "calib.json"
    path.write_text(
        json.dumps(
            {
                "model": wlc.MODEL_POLY,
                "coeffs": [400.0, 0.2],
                "n_pixels": 16,
                "fit_rms_nm": 0.01,
                "n_lines": 5,
                "lamp": "Hg-Ar",
                "created": "2026-09-04T00:00:00Z",
                "source_action_uuid": None,
            }
        )
    )
    calib = wlc.load(path)
    assert calib.wl_source == "unknown"
    assert wlc.evaluate(calib).shape == (16,)


def test_wl_source_round_trips_through_disk(tmp_path):
    counts = _synthetic_lamp(TRUE_COEFFS, N_PIXELS, LINE_PIXELS)
    lines = [_true_nm(p) for p in LINE_PIXELS]
    calib = wlc.fit_wavelength(counts, lines, degree=3, wl_source="spectrograph")
    path = tmp_path / "calib.json"
    wlc.save(calib, path)
    assert wlc.load(path).wl_source == "spectrograph"
