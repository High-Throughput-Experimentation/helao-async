"""String enums for Biologic IRange / ERange / Bandwidth, and their integer
values.

The aliases are what an action records and what the ``run_*`` endpoints
annotate, so their spellings are a contract; the integers are what
``BL_DefineIntParameter`` receives. Both live here so a reader can check one
against the other, and so nothing else in the driver has to know that
``"m1"`` means 7.

This module is hermetic. It used to lazy-import ``easy_biologic.lib.ec_lib``
just to map each alias onto a vendor member spelled identically, with the
import deferred because ``biologic_server.py`` imports this module on stations
that have EC-Lab but not easy-biologic. With the numbers held here there is
nothing to defer.
"""

from enum import StrEnum

from helao.deploy.hte.drivers.pstat.biologic import vendor


class EC_IRange(StrEnum):
    """String alias for Biologic current ranges (full-scale current).

    Attributes:
        p100: 100 pA range.
        n1: 1 nA range.
        n10: 10 nA range.
        n100: 100 nA range.
        u1: 1 uA range.
        u10: 10 uA range.
        u100: 100 uA range.
        m1: 1 mA range.
        m10: 10 mA range.
        m100: 100 mA range.
        a1: 1 A range.
        KEEP: Keep the previously configured current range.
        BOOSTER: External booster range.
        AUTO: Auto-range.
    """

    p100 = "p100"
    n1 = "n1"
    n10 = "n10"
    n100 = "n100"
    u1 = "u1"
    u10 = "u10"
    u100 = "u100"
    m1 = "m1"
    m10 = "m10"
    m100 = "m100"
    a1 = "a1"  # 1 amp

    KEEP = "KEEP"  # Keep previous I range
    BOOSTER = "BOOSTER"
    AUTO = "AUTO"


class EC_ERange(StrEnum):
    """String alias for Biologic voltage ranges (full-scale voltage).

    Attributes:
        v2_5: +/-2.5 V range.
        v5: +/-5 V range.
        v10: +/-10 V range.
        AUTO: Auto-range.
    """

    v2_5 = "v2_5"
    v5 = "v5"
    v10 = "v10"
    AUTO = "AUTO"


class EC_Bandwidth(StrEnum):
    """String alias for Biologic control-loop bandwidth settings.

    BW1 corresponds to the slowest stable bandwidth and BW7 to the fastest on
    standard hardware. BW8 and BW9 are only available on the SP-300 series.

    Attributes:
        BW1: Slow bandwidth.
        BW2: Bandwidth setting 2.
        BW3: Bandwidth setting 3.
        BW4: Bandwidth setting 4.
        BW5: Medium bandwidth.
        BW6: Bandwidth setting 6.
        BW7: Fast bandwidth.
        BW8: SP-300-only bandwidth setting.
        BW9: SP-300-only bandwidth setting.
    """

    BW1 = "BW1"  # "Slow"
    BW2 = "BW2"
    BW3 = "BW3"
    BW4 = "BW4"
    BW5 = "BW5"  # "Medium"
    BW6 = "BW6"
    BW7 = "BW7"  # "Fast"
    # NOTE: 8 and 9 only available for SP300 series
    BW8 = "BW8"
    BW9 = "BW9"


#: Alias -> vendor int. Spelled out rather than derived by `getattr` on a
#: vendor enum, because these numbers are the contract: they are what four
#: stations' recorded data was produced with, and a table can be diffed
#: against the PDF while a `getattr` cannot.
_IRANGE: dict[str, int] = {
    "p100": vendor.I_RANGE.I_RANGE_100pA,
    "n1": vendor.I_RANGE.I_RANGE_1nA,
    "n10": vendor.I_RANGE.I_RANGE_10nA,
    "n100": vendor.I_RANGE.I_RANGE_100nA,
    "u1": vendor.I_RANGE.I_RANGE_1uA,
    "u10": vendor.I_RANGE.I_RANGE_10uA,
    "u100": vendor.I_RANGE.I_RANGE_100uA,
    "m1": vendor.I_RANGE.I_RANGE_1mA,
    "m10": vendor.I_RANGE.I_RANGE_10mA,
    "m100": vendor.I_RANGE.I_RANGE_100mA,
    "a1": vendor.I_RANGE.I_RANGE_1A,
    "KEEP": vendor.I_RANGE.I_RANGE_KEEP,
    "BOOSTER": vendor.I_RANGE.I_RANGE_BOOSTER,
    "AUTO": vendor.I_RANGE.I_RANGE_AUTO,
}

_ERANGE: dict[str, int] = {
    "v2_5": vendor.E_RANGE.E_RANGE_2_5V,
    "v5": vendor.E_RANGE.E_RANGE_5V,
    "v10": vendor.E_RANGE.E_RANGE_10V,
    "AUTO": vendor.E_RANGE.E_RANGE_AUTO,
}

_BANDWIDTH: dict[str, int] = {f"BW{n}": vendor.BANDWIDTH(n) for n in range(1, 10)}


def ec_irange(value) -> int:
    """The vendor current-range int for a string alias or ``EC_IRange``."""
    return int(_IRANGE[EC_IRange(value).value])


def ec_erange(value) -> int:
    """The vendor voltage-range int for a string alias or ``EC_ERange``."""
    return int(_ERANGE[EC_ERange(value).value])


def ec_bandwidth(value) -> int:
    """The vendor bandwidth int for a string alias or ``EC_Bandwidth``."""
    return int(_BANDWIDTH[EC_Bandwidth(value).value])
