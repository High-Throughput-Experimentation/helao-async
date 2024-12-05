__all__ = ["HloStatus"]

from enum import Enum


class HloStatus(str, Enum):
    active = "active"
    finished = "finished"
    errored = "errored"
    aborted = "aborted"
    skipped = "skipped"
    estopped = "estopped"
    split = "split"
    busy = "busy"
    retired = "retired"
