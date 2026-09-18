"""The string aliases keep their spelling; only what they resolve to changes.

`EC_IRange`/`EC_ERange`/`EC_Bandwidth` are FastAPI annotations on the
`run_*` endpoints, so a renamed member changes the recorded action params and
the OpenAPI surface that `test_hte_route_checklist.py` freezes.
"""

import sys

import pytest

from helao.deploy.hte.drivers.pstat.biologic import vendor
from helao.deploy.hte.drivers.pstat.biologic.enum import (
    EC_Bandwidth,
    EC_ERange,
    EC_IRange,
    ec_bandwidth,
    ec_erange,
    ec_irange,
)


def test_the_irange_members_are_exactly_the_ones_the_endpoints_annotate():
    assert [m.value for m in EC_IRange] == [
        "p100",
        "n1",
        "n10",
        "n100",
        "u1",
        "u10",
        "u100",
        "m1",
        "m10",
        "m100",
        "a1",
        "KEEP",
        "BOOSTER",
        "AUTO",
    ]


def test_the_erange_and_bandwidth_members_are_unchanged():
    assert [m.value for m in EC_ERange] == ["v2_5", "v5", "v10", "AUTO"]
    assert [m.value for m in EC_Bandwidth] == [f"BW{i}" for i in range(1, 10)]


@pytest.mark.parametrize(
    "alias,expected",
    [
        ("p100", 0),
        ("n1", 1),
        ("n10", 2),
        ("n100", 3),
        ("u1", 4),
        ("u10", 5),
        ("u100", 6),
        ("m1", 7),
        ("m10", 8),
        ("m100", 9),
        ("a1", 10),
        ("KEEP", -1),
        ("BOOSTER", 11),
        ("AUTO", 12),
    ],
)
def test_irange_resolves_to_the_same_int_easy_biologic_sent(alias, expected):
    """Pinned by number, not by round-trip: these are the values four stations'
    recorded data was produced with."""
    assert ec_irange(alias) == expected
    assert ec_irange(EC_IRange(alias)) == expected


@pytest.mark.parametrize(
    "alias,expected", [("v2_5", 0), ("v5", 1), ("v10", 2), ("AUTO", 3)]
)
def test_erange_resolves_to_the_same_int(alias, expected):
    assert ec_erange(alias) == expected


@pytest.mark.parametrize("n", range(1, 10))
def test_bandwidth_resolves_to_its_own_number(n):
    assert ec_bandwidth(f"BW{n}") == n


def test_resolvers_return_plain_ints_not_enum_members():
    """`technique.py` puts these straight into an int ECC parameter."""
    assert type(ec_irange("AUTO")) is int
    assert type(ec_erange("AUTO")) is int
    assert type(ec_bandwidth("BW4")) is int


def test_every_resolved_value_is_a_real_vendor_enum_member():
    for member in EC_IRange:
        assert vendor.I_RANGE(ec_irange(member)) is not None
    for member in EC_ERange:
        assert vendor.E_RANGE(ec_erange(member)) is not None
    for member in EC_Bandwidth:
        assert vendor.BANDWIDTH(ec_bandwidth(member)) is not None


def test_an_unknown_alias_raises_rather_than_defaulting():
    with pytest.raises(ValueError):
        ec_irange("m1000")


def test_the_module_no_longer_touches_easy_biologic():
    assert "easy_biologic" not in sys.modules
