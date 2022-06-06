from enum import Enum


class TriggerType(int, Enum):
    fallingedge = 0
    risingedge = 1
