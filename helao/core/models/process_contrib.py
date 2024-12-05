__all__ = ["ProcessContrib"]
from enum import Enum


class ProcessContrib(str, Enum):
    action_params = "action_params"
    files = "files"
    samples_in = "samples_in"
    samples_out = "samples_out"
    run_use = "run_use"
    technique_name = "technique_name"
