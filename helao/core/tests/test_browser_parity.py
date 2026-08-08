"""Pytest guard over the parts of the rendered-parity lane that need no browser.

The checks themselves stay standalone ``__main__`` scripts -- they launch
orchestration groups and drive browsers, the class of thing that hangs a
collected pytest session. But the logic *underneath* them is pure: the contrast
arithmetic, the ink classifier, the matrix diff and its volatile-key policy,
and the config pair the diff depends on. None of that needs a browser, all of
it is load-bearing, and a lane whose diff silently stopped comparing anything
would still print "PASS".

So this file exists to pin the parts that can fail quietly, and in particular
to pin that the harness **can** fail: the mutation self-test here is the same
principle as P0's harness-fails-on-perturbation gate.
"""

import os

import pytest
import yaml

from helao.core.tests.browser_parity import matrix
from helao.core.tests.browser_parity.check_reflex_routes import (
    INK_AXES_ONLY,
    INK_DRAWN,
    WEBGL_BUDGET,
    classify_ink,
)
from helao.core.tests.browser_parity.probe import contrast

CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "deploy",
    "test",
    "configs",
)


def _load(name: str) -> dict:
    with open(os.path.join(CONFIG_DIR, name), encoding="utf-8") as handle:
        return yaml.safe_load(handle)


# ---------------------------------------------------------------------------
# Colour arithmetic
# ---------------------------------------------------------------------------
def test_contrast_of_black_on_white_is_the_wcag_maximum():
    assert contrast((0, 0, 0), (255, 255, 255)) == 21.0


def test_contrast_is_symmetric():
    assert contrast((3, 105, 161), (255, 255, 255)) == contrast(
        (255, 255, 255), (3, 105, 161)
    )


def test_contrast_of_a_colour_with_itself_is_one():
    assert contrast((187, 77, 0), (187, 77, 0)) == 1.0


def test_measured_semantic_button_clears_the_body_floor():
    """The real measurement from a live Bokeh operator, pinned.

    ``.bk-btn-danger`` rendered ``rgb(185,28,28)`` with white text. If the
    arithmetic here ever stopped agreeing with that, every contrast the lane
    reports would be wrong in the same direction and nothing would say so.
    """
    assert contrast((255, 255, 255), (185, 28, 28)) == 6.47


# ---------------------------------------------------------------------------
# Ink classification
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "distinct, expected",
    [
        (16717, "drawn"),  # measured: a chart with six data series
        (249, "axes-only"),  # measured: axes and labels, no data
        (3, "blank"),  # measured: a chart with no series at all
        (INK_DRAWN, "drawn"),
        (INK_DRAWN - 1, "axes-only"),
        (INK_AXES_ONLY, "axes-only"),
        (INK_AXES_ONLY - 1, "blank"),
    ],
)
def test_ink_bands_classify_the_measured_values(distinct, expected):
    assert classify_ink({"distinct": distinct, "ink": 0.5}) == expected


def test_ink_classifier_reports_a_capture_error_rather_than_a_bucket():
    """A canvas that could not be captured must not read as a bucket.

    Returning ``"blank"`` for a failed screenshot would turn an infrastructure
    problem into a rendering verdict -- in the direction that fails, which is
    survivable, but it would also let a *passing* run be built on captures that
    never happened if the bands were ever inverted.
    """
    assert classify_ink({"error": "no such canvas"}).startswith("error:")


def test_the_webgl_budget_stays_below_the_browsers_hard_cap():
    """Chrome evicts silently past 16, so a budget at 16 fails after the fact."""
    assert WEBGL_BUDGET < 16


# ---------------------------------------------------------------------------
# The matrix diff -- the part that must be able to fail
# ---------------------------------------------------------------------------
def _document() -> dict:
    return {
        "label": "legacy",
        "routes": {
            "operator": {
                "btn_danger_bg_rgb": [185, 28, 28],
                "btn_danger_contrast": 6.47,
                "doc_title": "Operator (legacy baseline)",
                "canvas0_ink_distinct": 5924,
                "canvas_painted_count": 5,
                "canvas_any_painted": True,
            }
        },
    }


def test_a_matrix_does_not_differ_from_itself():
    assert matrix.diff_matrices(_document(), _document()) == []


def test_perturbing_one_value_is_reported_and_nothing_else_is():
    mutated = matrix.perturb(_document(), "operator.btn_danger_bg_rgb", [0, 0, 0])
    differences = matrix.diff_matrices(_document(), mutated)
    assert [d[0] for d in differences] == ["operator.btn_danger_bg_rgb"]
    assert differences[0][1] == [185, 28, 28]
    assert differences[0][2] == [0, 0, 0]


def test_perturbing_a_tint_is_reported():
    """The tint is the value a stale bundle moves, so it must be compared."""
    document = {"label": "a", "routes": {"/live": {"tint_rgb": [240, 249, 255]}}}
    mutated = matrix.perturb(document, "/live.tint_rgb", [255, 255, 255])
    assert [d[0] for d in matrix.diff_matrices(document, mutated)] == ["/live.tint_rgb"]


@pytest.mark.parametrize(
    "key, value",
    [
        ("operator.doc_title", "Operator (hexagon generic graft)"),
        ("operator.canvas0_ink_distinct", 1),
        ("operator.canvas_painted_count", 4),
    ],
)
def test_declared_volatile_keys_are_excluded(key, value):
    assert (
        matrix.diff_matrices(_document(), matrix.perturb(_document(), key, value)) == []
    )


def test_a_route_present_on_only_one_side_is_a_difference():
    """Two configs drifting apart is exactly what this must not hide."""
    left = _document()
    right = {"label": "hexagon", "routes": {}}
    differences = matrix.diff_matrices(left, right)
    assert differences, "an absent route was silently ignored"
    assert all(d[2] is None for d in differences)


def test_perturbing_a_key_that_does_not_exist_raises():
    """A self-test that perturbs a missing key would prove nothing and pass."""
    with pytest.raises(KeyError):
        matrix.perturb(_document(), "operator.not_a_key", 1)


def test_the_volatile_list_is_short_and_every_entry_carries_a_reason():
    """Each exclusion is a hole in the gate, so each needs a stated reason."""
    assert len(matrix.VOLATILE_KEYS) <= 8
    for key, reason in matrix.VOLATILE_KEYS.items():
        assert reason and len(reason) > 15, f"{key} has no real reason"


def test_volatile_matching_is_by_suffix_not_by_equality():
    """Otherwise ``canvas7_ink_distinct`` is compared while ``canvas0`` is not."""
    document = {"label": "a", "routes": {"live": {"canvas7_ink_distinct": 10}}}
    mutated = matrix.perturb(document, "live.canvas7_ink_distinct", 999)
    assert matrix.diff_matrices(document, mutated) == []


# ---------------------------------------------------------------------------
# The config pair the Bokeh diff depends on
# ---------------------------------------------------------------------------
def test_the_bokeh_pair_declares_the_same_servers_on_the_same_ports():
    """If the pair drifts, the diff compares two different groups.

    A diff between a legacy config and a hexagon config that no longer describe
    the same group would report the *config* difference and read as a hosting
    regression -- or, worse, would be silenced by adding volatile keys until it
    passed. Pinning the shape here means drift fails as drift.
    """
    legacy = _load("goldenvis.yml")["servers"]
    hexagon = _load("goldenhexgraft.yml")["servers"]
    assert set(legacy) == set(hexagon)
    for key in legacy:
        assert legacy[key]["port"] == hexagon[key]["port"], key
        assert legacy[key]["group"] == hexagon[key]["group"], key


def test_the_legacy_baseline_names_no_hexagon_hosting():
    """The baseline is only a baseline if it is hosted the legacy way."""
    legacy = _load("goldenvis.yml")["servers"]
    for key, server in legacy.items():
        assert server.get("deployment") != "hexagon", key
        assert server.get("bokeh") != "graft", key
        assert "legacy_module" not in server, key


def test_the_hexagon_variant_actually_uses_the_graft():
    """And the other half is only a test of the graft if it uses the graft."""
    hexagon = _load("goldenhexgraft.yml")["servers"]
    grafted = [k for k, s in hexagon.items() if s.get("bokeh") == "graft"]
    assert grafted, "the hexagon variant grafts nothing"
    for key in grafted:
        assert hexagon[key]["deployment"] == "hexagon", key
        assert hexagon[key]["legacy_module"], key


def test_the_two_q10_configs_take_opposite_branches():
    """Q10 is only answered if one config declares a parser and one does not."""
    absent = _load("goldenreflex.yml")["servers"]["UI"]["params"]
    present = _load("goldenreflexspec.yml")["servers"]["UI"]["params"]
    assert "seqspec_parser_path" not in absent
    assert present["seqspec_parser_path"]
    assert present["seqspec_folder_path"]


def test_the_q10_variant_keeps_the_reflex_ports_of_its_sibling():
    """A different port would need a second bundle, i.e. a different build."""
    base = _load("goldenreflex.yml")["servers"]["UI"]
    variant = _load("goldenreflexspec.yml")["servers"]["UI"]
    assert base["port"] == variant["port"]


def test_the_fixture_spec_parser_satisfies_the_documented_contract():
    """``lister`` / ``PARAM_TYPES`` / ``list_params`` / ``parser``."""
    from helao.deploy.test.specifications.fixture_spec import SpecParser

    parser = SpecParser()
    for name in ("lister", "list_params", "parser"):
        assert callable(getattr(parser, name)), name
    assert parser.PARAM_TYPES

    folder = os.path.join(os.path.dirname(CONFIG_DIR), "specifications", "specs")
    files = parser.lister(folder)
    assert files, f"the fixture parser found no specs in {folder}"
    assert all(f.endswith(".json") for f in files)


def test_the_fixture_parser_params_intersect_a_real_sequence_signature():
    """Otherwise the Specs tab renders no fields and still looks correct."""
    import inspect

    from helao.deploy.test.sequences.TEST_seq import TEST_consecutive_noblocking
    from helao.deploy.test.specifications.fixture_spec import SpecParser

    declared = set(SpecParser().PARAM_TYPES)
    actual = set(inspect.getfullargspec(TEST_consecutive_noblocking).args)
    assert declared & actual, f"{declared} shares no parameter with {actual}"
