from enum import IntEnum


class TriggerType(IntEnum):
    fallingedge = 0
    risingedge = 1
    blip = 2
