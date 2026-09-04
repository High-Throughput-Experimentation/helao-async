"""`filter_allowed_additions` is asymmetric in exactly the way the risk is.

An `extra` route cannot break a client that relied on the frozen surface --
nobody knew it existed. A `missing` or `changed` route can. The frozen
checklist gate treats all three identically today, which is why a purely
additive change is as hard to land as a breaking one.

The tests that matter here are the two that pin a LISTED `missing` and a
LISTED `changed` still failing. They are the difference between an
asymmetric gate and a bypass.
"""

from harness.endpoints import filter_allowed_additions

EXTRA = {"path": "/ANDOR/calibrate_wl", "method": "post", "kind": "extra"}
MISSING = {"path": "/ANDOR/adjust_nd", "method": "post", "kind": "missing"}
CHANGED = {
    "path": "/ANDOR/acquire",
    "method": "post",
    "kind": "changed",
    "field": "params",
    "frozen": [],
    "current": [{"name": "x", "annotation": "int", "default": "1"}],
}
LISTS_CALIBRATE = [
    {
        "module": "andor_server.py",
        "path": "/ANDOR/calibrate_wl",
        "method": "post",
        "date": "2026-09-04",
        "why": "lamp wavelength calibration",
    }
]


def test_an_empty_allowlist_changes_nothing():
    failing, allowed = filter_allowed_additions([EXTRA, MISSING], [])
    assert failing == [EXTRA, MISSING]
    assert allowed == []


def test_a_listed_extra_is_allowed():
    failing, allowed = filter_allowed_additions([EXTRA], LISTS_CALIBRATE)
    assert failing == []
    assert allowed == [EXTRA]


def test_an_unlisted_extra_still_fails():
    other = {"path": "/ANDOR/something_else", "method": "post", "kind": "extra"}
    failing, allowed = filter_allowed_additions([other], LISTS_CALIBRATE)
    assert failing == [other]
    assert allowed == []


def test_a_listed_missing_still_fails():
    """An entry must not launder a removal into an addition."""
    listed = [{"path": MISSING["path"], "method": MISSING["method"]}]
    failing, allowed = filter_allowed_additions([MISSING], listed)
    assert failing == [MISSING]
    assert allowed == []


def test_a_listed_changed_still_fails():
    listed = [{"path": CHANGED["path"], "method": CHANGED["method"]}]
    failing, allowed = filter_allowed_additions([CHANGED], listed)
    assert failing == [CHANGED]
    assert allowed == []


def test_method_is_part_of_the_key():
    """A listed POST must not authorize a GET at the same path."""
    get_extra = {"path": "/ANDOR/calibrate_wl", "method": "get", "kind": "extra"}
    failing, allowed = filter_allowed_additions([get_extra], LISTS_CALIBRATE)
    assert failing == [get_extra]
    assert allowed == []


def test_mixed_diffs_split_cleanly():
    failing, allowed = filter_allowed_additions(
        [EXTRA, MISSING, CHANGED], LISTS_CALIBRATE
    )
    assert failing == [MISSING, CHANGED]
    assert allowed == [EXTRA]


def test_the_input_list_is_not_mutated():
    diffs = [EXTRA, MISSING]
    before = list(diffs)
    filter_allowed_additions(diffs, LISTS_CALIBRATE)
    assert diffs == before
