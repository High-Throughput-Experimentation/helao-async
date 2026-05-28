"""Enums describing orchestrator and dispatch-loop status and intent."""

__all__ = ["OrchStatus"]

from enum import Enum


class OrchStatus(str, Enum):
    """Top-level orchestrator state.

    Members:
        idle: Orchestrator has nothing in flight.
        error: Orchestrator is in an error state.
        busy: Orchestrator is processing a queue item.
        estopped: Orchestrator is halted by emergency stop.
    """

    idle = "idle"
    error = "error"
    busy = "busy"
    estopped = "estopped"


class LoopStatus(str, Enum):
    """State of the orchestrator's dispatch loop.

    Members:
        started: Loop is running.
        estopped: Loop halted by emergency stop.
        stopped: Loop stopped normally.
        error: Loop terminated due to an error.
    """

    started = "started"
    estopped = "estopped"
    stopped = "stopped"
    error = "error"


class LoopIntent(str, Enum):
    """Requested transition for the dispatch loop.

    Members:
        estop: Request emergency stop.
        skip: Skip the current item.
        stop: Stop after the current item.
        none: No pending intent.
    """

    estop = "estop"
    skip = "skip"
    stop = "stop"
    none = "none"
