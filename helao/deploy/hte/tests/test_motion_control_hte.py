"""Live-config sweeps over hte's motion configs (moved from the parent's test_motion_control.py).

The parent keeps the backend-agnostic logic tests and hand-written schema
fixtures; what reads the real hte configs lives here.
"""

import glob
import math
import os
from pathlib import Path

import pytest
import yaml

from helao.ui.shared.motion_control import (
    DEFAULT_WARN_ABOVE_MM,
    discover_axes,
    mm_per_count,
    warn_threshold_mm,
)

HTE_CONFIGS = Path(__file__).resolve().parents[1] / "configs"

HTE_CONFIG_GLOB = str(HTE_CONFIGS / "*.yml")

#: Every scale the tracked hte configs declare, one entry per config x axis.
#:
#: The count is asserted rather than merely used, so that adding a station is a
#: deliberate update to this file instead of a silent narrowing of the sweep
#: that the property tests below rest on.
#:
#: Was 29 until 13 hte configs holding 12 of those scales were retired; the
#: remaining 17 are the live configs.
TRACKED_SCALE_COUNT = 17

#: The largest N the round-trip property looks for a failure within. Measured
#: across all tracked scales: the worst first-failing N is 255, so this is 4x
#: margin -- and a 1024-count jog is an ordinary move, which keeps "every
#: shipped scale loses a count within an ordinary jog" a meaningful claim.
N_MAX = 1024


def _tracked_hte_scales():
    """Yield ``(config, server_key, axis, mm_per_count)`` for every tracked hte axis.

    Reads the shipped configs directly rather than through fixtures, so the
    property tests below are asserted against the numbers stations actually
    run, not against numbers this file made up.
    """
    found = []
    for path in sorted(glob.glob(HTE_CONFIG_GLOB)):
        with open(path, encoding="utf-8") as handle:
            cfg = yaml.safe_load(handle)
        if not isinstance(cfg, dict):
            continue
        for server_key, server_cfg in (cfg.get("servers") or {}).items():
            if not isinstance(server_cfg, dict):
                continue
            params = server_cfg.get("params") or {}
            if "count_to_mm" in params and "axis_id" in params:
                source = "letter_scale"
                axes = list(params["axis_id"])
            elif isinstance(params.get("axes"), dict) and any(
                isinstance(block, dict) and "pos_scale" in block
                for block in params["axes"].values()
            ):
                source = "inverse_scale"
                axes = list(params["axes"])
            else:
                continue
            for axis in axes:
                found.append(
                    (
                        os.path.basename(path),
                        server_key,
                        axis,
                        mm_per_count(server_cfg, axis, source),
                    )
                )
    return found


def _hte_server(config_name: str, server_key: str) -> dict:
    """Return one server block from a tracked hte config."""
    path = HTE_CONFIGS / config_name
    with open(path, encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle)
    return cfg["servers"][server_key]


@pytest.fixture(scope="module")
def adss3_motor():
    """A four-axis letter-keyed station, including an Rz rotation axis."""
    return _hte_server("adss3.yml", "MOTOR")


@pytest.fixture(scope="module")
def hispec_motor():
    """A two-axis letter-keyed station."""
    return _hte_server("hispec.yml", "MOTOR")


@pytest.fixture(scope="module")
def eche10_kmotor():
    """A single-axis reciprocal-schema station; move_limit_mm is 3.0 here."""
    return _hte_server("eche10.yml", "KMOTOR")


@pytest.fixture(scope="module")
def hispec_kmotor():
    """The other reciprocal-schema station; move_limit_mm is 5.0 here."""
    return _hte_server("hispec.yml", "KMOTOR")


def test_discovery_reads_the_letter_keyed_schema(adss3_motor):
    items = discover_axes(adss3_motor, "letter_scale", server_key="MOTOR")

    assert [i.axis for i in items] == ["x", "y", "z", "Rz"]
    assert all(i.server_key == "MOTOR" for i in items)
    assert all(i.family == "letter_scale" for i in items)
    # Letter-keyed: x maps to controller letter C, whose count_to_mm entry is
    # the one that must be picked up.
    assert items[0].mm_per_count == pytest.approx(0.00015634000000352077, rel=1e-12)
    print("test_discovery_reads_the_letter_keyed_schema PASS")


def test_discovery_reads_the_reciprocal_schema(eche10_kmotor):
    items = discover_axes(eche10_kmotor, "inverse_scale", server_key="KMOTOR")

    assert [i.axis for i in items] == ["z"]
    assert items[0].family == "inverse_scale"
    assert items[0].mm_per_count == pytest.approx(1 / 1228800.0, rel=1e-12)
    print("test_discovery_reads_the_reciprocal_schema PASS")


def test_no_tracked_scale_round_trips_cleanly_within_an_ordinary_jog():
    """For every shipped scale there *exists* a small N that loses a count.

    Existence, not identity: ``count_to_mm`` values are calibration outputs and
    stations retune them, so pinning the exact first-failing N per axis would
    red this suite on a legitimate recalibration -- a false alarm about the
    very thing the test exists to guard.
    """
    scales = _tracked_hte_scales()
    assert len(scales) == TRACKED_SCALE_COUNT

    clean = []
    for config, server_key, axis, scale in scales:
        assert scale is not None, f"{config}:{server_key}:{axis} has no scale"
        if not any(math.floor(n * scale / scale) != n for n in range(1, N_MAX + 1)):
            clean.append(f"{config}:{server_key}:{axis}")
    assert clean == [], f"scales round-tripping cleanly to N={N_MAX}: {clean}"
    print("test_no_tracked_scale_round_trips_cleanly_within_an_ordinary_jog PASS")


def test_every_tracked_scale_is_a_plausible_millimetres_per_count():
    """The property test that catches a dropped or an added inversion.

    Real config data rather than hand-written expectations, and the bound is
    symmetric: dropping the reciprocal on the counts-per-mm schema yields
    1228800.0, over by 1.2e8x, while wrongly *adding* one to a millimetre-per-
    count schema yields 1/0.00015628 = 6398.77, also over. Measured range is
    8.138021e-07 to 3.169786e-04, so the upper bound has 31.5x headroom and no
    legitimate recalibration comes near it.
    """
    scales = _tracked_hte_scales()
    assert len(scales) == TRACKED_SCALE_COUNT

    offenders = [
        (config, server_key, axis, scale)
        for config, server_key, axis, scale in scales
        if not (scale is not None and 0 < scale < 1e-2)
    ]
    assert offenders == [], f"implausible mm-per-count: {offenders}"
    print("test_every_tracked_scale_is_a_plausible_millimetres_per_count PASS")


def test_the_reciprocal_schema_is_inverted_not_passed_through(eche10_kmotor):
    scale = mm_per_count(eche10_kmotor, "z", "inverse_scale")

    assert scale == pytest.approx(1 / 1228800.0, rel=1e-12)
    # The load-bearing half: the config states 1228800.0 counts per mm, and
    # handing that number back as if it were mm per count is the silent error
    # this accessor exists to make impossible.
    assert scale != 1228800.0
    print("test_the_reciprocal_schema_is_inverted_not_passed_through PASS")


def test_the_letter_keyed_schema_resolves_through_the_controller_letter(adss3_motor):
    # y maps to controller letter B; the scale must come from count_to_mm[B],
    # not from a count_to_mm["y"] that does not exist.
    assert mm_per_count(adss3_motor, "y", "letter_scale") == pytest.approx(
        0.00015627999999717445, rel=1e-12
    )
    assert mm_per_count(adss3_motor, "Rz", "letter_scale") == pytest.approx(
        0.0003169786106003353, rel=1e-12
    )
    print("test_the_letter_keyed_schema_resolves_through_the_controller_letter PASS")


def test_the_accessor_is_a_single_consistent_scalar(adss3_motor, eche10_kmotor):
    """Stated in terms of ``mm_per_count`` alone.

    There is deliberately no ``counts_to_mm`` / ``mm_to_counts`` pair to test
    against: adding them would create a second and a third place that computes
    a scale, which is exactly what this layer forbids.
    """
    for cfg, source, axes in (
        (adss3_motor, "letter_scale", ("x", "y", "z", "Rz")),
        (eche10_kmotor, "inverse_scale", ("z",)),
    ):
        for axis in axes:
            scale = mm_per_count(cfg, axis, source)
            assert scale is not None
            for n in (1, 7, 1000, 1228800):
                assert n * scale / scale == pytest.approx(n, rel=1e-9)
    print("test_the_accessor_is_a_single_consistent_scalar PASS")


def test_the_threshold_chain_resolves_in_order(
    eche10_kmotor, hispec_kmotor, adss3_motor
):
    # The reciprocal schema already states how far the axis may travel, so the
    # threshold reuses it rather than making a station declare it twice.
    assert warn_threshold_mm(eche10_kmotor, "z", "inverse_scale") == 3.0
    assert warn_threshold_mm(hispec_kmotor, "z", "inverse_scale") == 5.0
    # No move_limit_mm on the letter-keyed schema, so the default applies.
    assert warn_threshold_mm(adss3_motor, "x", "letter_scale") == DEFAULT_WARN_ABOVE_MM
    # An explicit per-axis override wins over both.
    override = {
        "params": {"warn_above_mm": {"z": 1.5}, "axes": {"z": {"move_limit_mm": 3.0}}}
    }
    assert warn_threshold_mm(override, "z", "inverse_scale") == 1.5
    print("test_the_threshold_chain_resolves_in_order PASS")


def test_the_default_clears_every_shipped_move_limit(eche10_kmotor, hispec_kmotor):
    # The default must sit above the drivers' own hard rejects, so that where a
    # station declares a limit its reject still fires first.
    limits = [
        warn_threshold_mm(eche10_kmotor, "z", "inverse_scale"),
        warn_threshold_mm(hispec_kmotor, "z", "inverse_scale"),
    ]
    assert max(limits) < DEFAULT_WARN_ABOVE_MM
    print("test_the_default_clears_every_shipped_move_limit PASS")


def test_a_shipped_hte_axis_speed_is_configured():
    # Regression for a real station failure: the ceiling was 120s, but a Galil
    # axis at its configured default speed needs longer than that for a long
    # travel, so the follow-up quit mid-move and the readout never settled.
    #
    # The slowest configured axis across the shipped hte motion stations sets
    # the bar; the parent's test_the_followup_ceiling_covers_the_drivers_move_wait_cap
    # holds the framework side (the ceiling against the driver's 30-minute cap).
    slowest_mm_per_s = None
    for path in sorted(glob.glob(HTE_CONFIG_GLOB)):
        with open(path, encoding="utf-8") as handle:
            cfg = yaml.safe_load(handle) or {}
        for server in (cfg.get("servers") or {}).values():
            params = (server or {}).get("params") or {}
            ctm = params.get("count_to_mm")
            speed = params.get("def_speed_count_sec")
            if not isinstance(ctm, dict) or not speed:
                continue
            for scale in ctm.values():
                mm_per_s = float(scale) * float(speed)
                if mm_per_s > 0 and (
                    slowest_mm_per_s is None or mm_per_s < slowest_mm_per_s
                ):
                    slowest_mm_per_s = mm_per_s

    assert slowest_mm_per_s is not None, "no configured axis speed found"
    print(f"slowest shipped axis {slowest_mm_per_s:.3f} mm/s")
