"""Enum types for the HTE motion drivers."""

from enum import Enum


class MoveModes(str, Enum):
    """Motor move mode used by the Galil motion driver.

    Attributes:
        homing: Move toward and zero against a limit switch.
        relative: Move by an offset from the current position.
        absolute: Move to an absolute coordinate.
    """

    homing = "homing"
    relative = "relative"
    absolute = "absolute"


class TransformationModes(str, Enum):
    """Coordinate frame in which a motion request is expressed.

    Attributes:
        motorxy: Raw motor-axis coordinates (no transform applied).
        platexy: Coordinates on the sample plate; converted via the plate
            calibration matrix before being sent to the motors.
        instrxy: Coordinates in the instrument frame; converted via the
            instrument calibration matrix.
    """

    motorxy = "motorxy"
    platexy = "platexy"
    instrxy = "instrxy"
