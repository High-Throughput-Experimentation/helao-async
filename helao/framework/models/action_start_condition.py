"""Enum of gating conditions the orchestrator applies before dispatching an action."""

__all__ = ["ActionStartCondition"]

from enum import Enum


class ActionStartCondition(int, Enum):
    """Pre-dispatch wait condition for an action.

    Members:
        no_wait: Dispatch immediately without waiting on anything.
        wait_for_endpoint: Wait until the target endpoint is free.
        wait_for_server: Wait until the target action server is free.
        wait_for_all: Wait until all queued actions have finished.
        wait_for_orch: Wait until any pending "wait" action on the orch finishes.
        wait_for_previous: Wait only for the most recently dispatched action.
    """

    no_wait = 0  # orch is dispatching an unconditional action
    wait_for_endpoint = 1  # orch is waiting for endpoint to become available
    wait_for_server = 2  # orch is waiting for server to become available
    wait_for_all = 3  # (or other): orch is waiting for all action_dq to finish
    wait_for_orch = 4  # orch is waiting for "wait" action on orch to finish
    wait_for_previous = 5  # orch waits for last dispatched action only
