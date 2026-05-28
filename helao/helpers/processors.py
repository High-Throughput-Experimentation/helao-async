"""Abstract base classes for HLO file and metadata processors.

Consolidates the former hlo_postprocessor and meta_processor modules.
"""

__all__ = ["HloPostProcessor", "MetaProcessor"]

import os
from abc import ABC, abstractmethod
from glob import glob
from typing import List

from helao.core.models.file import FileInfo

from .premodels import Action


class HloPostProcessor(ABC):

    def __init__(self, action: Action, save_root: str):
        self.action = action
        if action.manual_action:
            save_root = str(save_root).replace("RUNS_ACTIVE", "RUNS_DIAG")
        self.output_dir = os.path.join(save_root, action.action_output_dir)
        exp_dir = os.path.dirname(self.output_dir)
        exp_yml_paths = glob(os.path.join(exp_dir, "*.yml"))
        self.exp_yml_path = exp_yml_paths[0] if exp_yml_paths else None
        seq_dir = os.path.dirname(exp_dir)
        seq_yml_paths = glob(os.path.join(seq_dir, "*.yml"))
        self.seq_yml_path = seq_yml_paths[0] if seq_yml_paths else None
        self.files = action.files

    @abstractmethod
    def process(self) -> List[FileInfo]:
        """Return updated list of all action files, after post-processing."""


class MetaProcessor(ABC):

    def __init__(self, meta, core):
        self.core = core
        self.meta = meta
        self.meta_type = meta.__class__.__name__.lower()
        self.global_params = (
            core.global_params if core.__class__.__name__.lower() == "orch" else {}
        )

    @abstractmethod
    def process(self) -> None:
        """Update object in-place."""
