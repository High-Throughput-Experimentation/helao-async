"""Caption -> EClib2 enum coercion, without the vendor SDK present.

``biologic_eclib2.enum`` is the seam between the plain strings an action sends
("m1", "AUTO", "BW5") and the ``IRangeValue`` / ``IRangeMode`` / ``ERangeValue``
/ ``BandwidthValue`` members EClib2 wants. It must import and answer with no SDK
installed, so it yields member *names* and leaves resolution to the vendor
loader.

The interesting case is IRange: EClib1 carried AUTO and KEEP as IRange values,
while EClib2 splits them into a separate ``IRangeMode`` passed alongside a value
(``BL_SetIRange(handle, mode, value)``). So one caption maps to a pair.
"""

import pytest

from helao.deploy.hte.drivers.pstat.biologic_eclib2 import enum as ec2


def test_the_module_imports_without_the_vendor_sdk():
    # Nothing here may reach the DLL or the vendor package.
    assert ec2.irange_plan("m1")
    assert ec2.erange_name("v5")
    assert ec2.bandwidth_name("BW5")


@pytest.mark.parametrize(
    "caption,value_name",
    [
        ("p100", "EC_SDK_IRANGE_100pA"),
        ("n1", "EC_SDK_IRANGE_1nA"),
        ("n10", "EC_SDK_IRANGE_10nA"),
        ("n100", "EC_SDK_IRANGE_100nA"),
        ("u1", "EC_SDK_IRANGE_1uA"),
        ("u10", "EC_SDK_IRANGE_10uA"),
        ("u100", "EC_SDK_IRANGE_100uA"),
        ("m1", "EC_SDK_IRANGE_1mA"),
        ("m10", "EC_SDK_IRANGE_10mA"),
        ("m100", "EC_SDK_IRANGE_100mA"),
        ("a1", "EC_SDK_IRANGE_1A"),
    ],
)
def test_a_fixed_current_range_maps_to_fixed_mode_and_its_own_value(
    caption, value_name
):
    assert ec2.irange_plan(caption) == ("I_RANGE_MODE_FIXED", value_name)


def test_booster_is_a_fixed_range_not_a_mode():
    # EClib1 spelled BOOSTER alongside AUTO/KEEP; in EClib2 it is an ordinary
    # IRangeValue, so it stays in FIXED mode.
    assert ec2.irange_plan("BOOSTER") == (
        "I_RANGE_MODE_FIXED",
        "EC_SDK_IRANGE_BOOSTER",
    )


def test_auto_becomes_a_mode_and_still_carries_a_seed_value():
    # BL_SetIRange takes a value even in AUTO mode; the vendor's own example
    # passes EC_SDK_IRANGE_1mA there. The seed is explicit, never invented at
    # the call site.
    assert ec2.irange_plan("AUTO") == ("I_RANGE_MODE_AUTO", "EC_SDK_IRANGE_1mA")
    assert ec2.irange_plan("AUTO", auto_seed="u100") == (
        "I_RANGE_MODE_AUTO",
        "EC_SDK_IRANGE_100uA",
    )


def test_keep_becomes_a_mode_and_its_value_is_ignored_but_still_valid():
    mode, value_name = ec2.irange_plan("KEEP")
    assert mode == "I_RANGE_MODE_KEEP"
    assert value_name in ec2.IRANGE_VALUE_NAMES.values()


def test_an_auto_seed_may_not_itself_be_a_mode_caption():
    # "AUTO" as its own seed would recurse into nothing resolvable.
    with pytest.raises(ValueError, match="auto_seed"):
        ec2.irange_plan("AUTO", auto_seed="AUTO")


@pytest.mark.parametrize(
    "caption,name",
    [
        ("v2_5", "EC_SDK_ERANGE_2_5"),
        ("v5", "EC_SDK_ERANGE_5"),
        ("v10", "EC_SDK_ERANGE_10"),
        ("AUTO", "EC_SDK_ERANGE_AUTO"),
    ],
)
def test_every_erange_caption_has_a_real_eclib2_member(caption, name):
    # Unlike the .mps text path, EClib2 has a genuine AUTO member here, so no
    # caption needs special-casing.
    assert ec2.erange_name(caption) == name


@pytest.mark.parametrize("n", range(1, 10))
def test_bandwidth_captions_map_positionally(n):
    assert ec2.bandwidth_name(f"BW{n}") == f"EC_SDK_BANDWIDTH_{n}"


def test_there_is_no_bandwidth_keep_caption():
    # The docs' constants table lists EC_SDK_BANDWIDTH_KEEP, but the shipped
    # BandwidthValue enum has only 1..9 -- and EClib1's EC_Bandwidth had no
    # KEEP either. Accepting the caption would resolve to nothing at the
    # station. Omit `Bandwidth` to leave the channel alone.
    with pytest.raises(ValueError, match="KEEP"):
        ec2.bandwidth_name("KEEP")


@pytest.mark.parametrize(
    "fn,bad",
    [
        ("irange_plan", "m2"),
        ("erange_name", "v3"),
        ("bandwidth_name", "BW10"),
    ],
)
def test_an_unknown_caption_raises_rather_than_defaulting(fn, bad):
    # Silently defaulting a mistyped range would run the cell at the wrong
    # scale and record it as if it were asked for.
    with pytest.raises(ValueError, match=bad):
        getattr(ec2, fn)(bad)


def test_captions_cover_exactly_the_eclib1_surface():
    # The whole point of this backend is drop-in parity, so the caption set has
    # to match what biologic/enum.py's EC_IRange already accepts. Spelled out
    # rather than imported: biologic/enum.py imports easy_biologic eagerly and
    # would not load here.
    eclib1_irange = {
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
    }
    assert set(ec2.IRANGE_CAPTIONS) == eclib1_irange
    assert set(ec2.ERANGE_CAPTIONS) == {"v2_5", "v5", "v10", "AUTO"}
    assert set(ec2.BANDWIDTH_CAPTIONS) == {f"BW{n}" for n in range(1, 10)}
