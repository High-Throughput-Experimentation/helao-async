# helao/core/tests/test_shared_platemap.py
"""The plate-map helpers, after the hoist out of the Reflex operator.

Two of these pin properties the composition page depends on and the operator
never exercised: that `platemap_rows` keys on the platemap's own `sample_no`
rather than on the row's position, and that `plate_api_for_config` keeps the
operator's opt-in gate while needing no single server key.
"""

import pytest

from helao.ui.shared import platemap

#: A platemap whose own sample numbers deliberately disagree with the row
#: order: row 0 is sample 5, row 1 is sample 2. `platemap_points` numbers these
#: 1 and 2; `platemap_rows` must call them 5 and 2.
PM = [
    {"sample_no": 5, "x": 1.0, "y": 2.0, "code": 0, "A": 0.5, "B": 0.5},
    {"sample_no": 2, "x": 3.0, "y": 4.0, "code": 0, "A": 1.0},
    {"sample_no": 9, "x": "not a number", "y": 6.0},
]


def test_platemap_rows_keys_on_the_maps_own_sample_no() -> None:
    rows = platemap.platemap_rows(PM)
    assert [row["sample_no"] for row in rows] == [5, 2]


def test_platemap_rows_drops_a_row_with_an_unusable_coordinate() -> None:
    """Dropped whole, as `platemap_points` already does. Handing a string to
    `plots` raises from inside the render and takes the chart down."""
    rows = platemap.platemap_rows(PM)
    assert len(rows) == 2
    assert 9 not in [row["sample_no"] for row in rows]


def test_platemap_rows_and_platemap_points_disagree_about_numbering() -> None:
    """The whole reason `platemap_rows` exists, asserted rather than assumed."""
    _, _, positional = platemap.platemap_points(PM)
    from_map = [row["sample_no"] for row in platemap.platemap_rows(PM)]
    assert positional == [1, 2]
    assert from_map == [5, 2]
    assert positional != from_map


def test_platemap_rows_carries_the_original_entry() -> None:
    rows = platemap.platemap_rows(PM)
    assert rows[0]["entry"]["A"] == 0.5


def test_platemap_rows_on_an_empty_map() -> None:
    assert platemap.platemap_rows(None) == []
    assert platemap.platemap_rows([]) == []


def test_plate_api_for_config_returns_none_when_no_server_declares_one() -> None:
    cfg = {"servers": {"ORCH": {"params": {}}, "MOTOR": {}}}
    assert platemap.plate_api_for_config(cfg) is None


def test_plate_api_for_config_finds_the_server_that_declares_one(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(
        platemap,
        "plate_api_for",
        lambda cfg: sentinel if (cfg or {}).get("params") else None,
    )
    cfg = {"servers": {"ORCH": {}, "XRFS": {"params": {"plate_api": "HTEPlateAPI"}}}}
    assert platemap.plate_api_for_config(cfg) is sentinel


def test_plate_api_for_config_tolerates_a_config_without_servers() -> None:
    assert platemap.plate_api_for_config({}) is None
    assert platemap.plate_api_for_config(None) is None


def test_nearest_sample_still_works_after_the_hoist() -> None:
    assert platemap.nearest_sample(PM, 2.9, 4.1) == 2


def test_the_operator_still_exposes_every_hoisted_name() -> None:
    """The hoist must be invisible to the operator's own call sites and to the
    tests that reach these through `helao.ui.reflex.operator`."""
    from helao.ui.reflex import operator

    for name in (
        "FRACTION_KEYS",
        "PLATE_APIS",
        "plate_api_for",
        "platemap_points",
        "nearest_sample",
        "composition_text",
        "sample_summary",
    ):
        assert hasattr(operator, name), name
