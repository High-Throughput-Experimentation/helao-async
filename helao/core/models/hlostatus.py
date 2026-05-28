"""Enum describing the lifecycle status of HELAO actions, experiments, and sequences."""

__all__ = ["HloStatus"]

from enum import Enum


class HloStatus(str, Enum):
    """Lifecycle status flags applied to actions, experiments, and sequences.

    Members:
        active: Currently running.
        finished: Completed normally.
        errored: Terminated due to an error.
        aborted: Terminated by user/operator request.
        skipped: Skipped without running.
        estopped: Halted by an emergency stop.
        split: Split into sub-actions.
        busy: Server/endpoint busy but action not yet started.
        retired: Archived/no longer active.
    """

    active = "active"
    finished = "finished"
    errored = "errored"
    aborted = "aborted"
    skipped = "skipped"
    estopped = "estopped"
    split = "split"
    busy = "busy"
    retired = "retired"
