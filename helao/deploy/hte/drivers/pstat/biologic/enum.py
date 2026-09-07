"""String enums mirroring easy-biologic IRange / ERange / Bandwidth values.

Provides serializable ``StrEnum`` aliases plus resolver functions that map
each alias to the corresponding ``easy_biologic.lib.ec_lib`` enum member, so
the rest of the driver can accept plain strings from configs and actions.

The vendor import is deliberately lazy. ``biologic_server.py`` imports this
module, and a station running the OLE COM backend has EC-Lab but not
necessarily easy-biologic -- an eager import here made that station's action
server unimportable.
"""

from enum import StrEnum
from functools import lru_cache


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


def _ec_lib():
    """The vendor enum module, imported on first use.

    Imported lazily because ``biologic_server.py`` imports this module, and a
    station running the OLE COM backend has EC-Lab but not necessarily
    easy-biologic. An eager import there made that station's action server
    unimportable. ``driver.py`` and ``technique.py`` were made hermetic in
    P3a-2; this module was missed because nothing then needed it to be.
    """
    from easy_biologic.lib.ec_lib import Bandwidth, ERange, IRange

    return IRange, ERange, Bandwidth


@lru_cache(maxsize=1)
def _maps() -> tuple:
    """The vendor ``(IRange, ERange, Bandwidth)`` classes, cached on first use.

    Resolved per member rather than built into eager dicts: every
    ``EC_IRange``/``EC_ERange``/``EC_Bandwidth`` member's value is spelled
    identically to the vendor member's name, so ``getattr`` on the cached
    vendor class is all a lookup needs. Building full dicts here would force
    every alias to resolve against the vendor package on the very first call
    (and on every model the map is used with), which is more than "resolve
    against the vendor package only when called" requires.
    """
    return _ec_lib()


def ec_irange(value):
    """The vendor ``IRange`` member for a string alias or ``EC_IRange``."""
    IRange, _, _ = _maps()
    return getattr(IRange, EC_IRange(value).value)


def ec_erange(value):
    """The vendor ``ERange`` member for a string alias or ``EC_ERange``."""
    _, ERange, _ = _maps()
    return getattr(ERange, EC_ERange(value).value)


def ec_bandwidth(value):
    """The vendor ``Bandwidth`` member for a string alias or ``EC_Bandwidth``."""
    _, _, Bandwidth = _maps()
    return getattr(Bandwidth, EC_Bandwidth(value).value)
