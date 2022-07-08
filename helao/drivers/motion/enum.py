from enum import Enum


class MoveModes(str, Enum):
    homing = "homing"
    relative = "relative"
    absolute = "absolute"


class TransformationModes(str, Enum):
    motorxy = "motorxy"
    platexy = "platexy"
    instrxy = "instrxy"
