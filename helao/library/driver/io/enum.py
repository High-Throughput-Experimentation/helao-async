from enum import Enum


class TriggerType(str, Enum):
    risingedge = "risingedge"
    fallingedge = "fallingedge"
