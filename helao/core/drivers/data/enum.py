from enum import Enum


class YmlType(str, Enum):
    action = "action"
    experiment = "experiment"
    sequence = "sequence"
