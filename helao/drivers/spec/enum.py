from enum import Enum


class SpecTrigType(int, Enum):
    off = 10
    internal = 11
    external = 12

class SpecType(str, Enum):
    T = "T"
    R = "R"
    
class ReferenceMode(str, Enum):
    internal = "internal"  # measure nearest references to starting and ending samples
    builtin = "builtin"  # measure reference position defined in config
    blank = "blank"  # measure starting and ending samples w/auto-stop for plate swap