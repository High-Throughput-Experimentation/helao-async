__all__ = ["OrchStatus"]

from enum import Enum


class OrchStatus(str, Enum):
    idle = "idle"
    error = "error"
    busy = "busy"
    estopped = "estopped"


class LoopStatus(str, Enum):
    started = "started"
    estopped = "estopped"
    stopped = "stopped"
    error = "error"

class LoopIntent(str, Enum):
    estop = "estop"
    skip = "skip"
    stop = "stop"
    none = "none"