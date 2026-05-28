"""Shared enums for data-driver modules."""

from enum import Enum


class YmlType(str, Enum):
    """Top-level kinds of HELAO YAML records."""

    action = "action"
    experiment = "experiment"
    sequence = "sequence"
