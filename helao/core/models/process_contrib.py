"""Enum identifying which action fields contribute to an aggregated process record."""

__all__ = ["ProcessContrib"]
from enum import Enum


class ProcessContrib(str, Enum):
    """Fields an action can contribute to its enclosing process.

    Members:
        action_params: Action parameter dict.
        files: Files produced by the action.
        samples_in: Input samples.
        samples_out: Output samples.
        run_use: `RunUse` tag.
        technique_name: Technique name.
    """

    action_params = "action_params"
    files = "files"
    samples_in = "samples_in"
    samples_out = "samples_out"
    run_use = "run_use"
    technique_name = "technique_name"
