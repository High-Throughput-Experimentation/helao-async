from enum import StrEnum
from easy_biologic.lib.ec_lib import IRange, ERange


class EC_IRange( StrEnum ):
    """
    Current ranges.
    """
    p100 =  "p100"
    n1   =  "n1"
    n10  =  "n10"
    n100 =  "n100"
    u1   =  "u1"
    u10  =  "u10"
    u100 =  "u100"
    m1   =  "m1"
    m10  =  "m10"
    m100 =  "m100"
    a1   =  "a1"      # 1 amp

    KEEP    = "KEEP"    # Keep previous I range
    BOOSTER = "BOOSTER"
    AUTO    = "AUTO"


class EC_ERange( StrEnum ):
    """
    Voltage ranges
    """
    v2_5 = "v2_5"
    v5   = "v5"
    v10  = "v10"
    AUTO = "AUTO"


EC_IRange_map = {
    EC_IRange.p100: IRange.p100.value,
    EC_IRange.n1: IRange.n1.value,
    EC_IRange.n10: IRange.n10.value,
    EC_IRange.n100: IRange.n100.value,
    EC_IRange.u1: IRange.u1.value,
    EC_IRange.u10: IRange.u10.value,
    EC_IRange.u100: IRange.u100.value,
    EC_IRange.m1: IRange.m1.value,
    EC_IRange.m10: IRange.m10.value,
    EC_IRange.m100: IRange.m100.value,
    EC_IRange.a1: IRange.a1.value,
    EC_IRange.KEEP: IRange.KEEP.value,
    EC_IRange.BOOSTER: IRange.BOOSTER.value,
    EC_IRange.AUTO: IRange.AUTO.value,
}

EC_ERange_map = {
    EC_ERange.v2_5: ERange.v2_5.value,
    EC_ERange.v5: ERange.v5.value,    
    EC_ERange.v10: ERange.v10.value,  
    EC_ERange.AUTO: ERange.AUTO.value,
}