"""Abstract base classes for HLO file and metadata post-processors.

Defines :class:`HloPostProcessor` for transforming an action's on-disk
output files after completion and :class:`MetaProcessor` for in-place
mutation of metadata objects such as ``Action``/``Experiment``/``Sequence``.
"""

__all__ = ["HloPostProcessor", "MetaProcessor"]

import os
from abc import ABC, abstractmethod
from glob import glob

from helao.core.models.file import FileInfo
from helao.core.models.run_dir import RunDir

from .premodels import Action


class HloPostProcessor(ABC):
    """Abstract base for post-processing an action's HLO output files.

    Subclasses implement :meth:`process` to transform, summarize, or augment
    the files written by an action and return an updated file list.

    Attributes:
        action: The completed action whose outputs are being processed.
        output_dir: Filesystem directory containing the action's outputs.
        exp_yml_path: Path to the parent experiment YAML, if found.
        seq_yml_path: Path to the parent sequence YAML, if found.
        files: The action's current file list (input to processing).
    """

    def __init__(self, action: Action, save_root: str):
        """Resolve experiment/sequence YAML paths relative to the action output.

        Args:
            action: The completed action to post-process.
            save_root: Root directory under which action outputs live; the
                ``RUNS_ACTIVE`` segment is rewritten to ``RUNS_DIAG`` when
                ``action.manual_action`` is set.
        """
        self.action = action
        if action.manual_action:
            save_root = str(save_root).replace(RunDir.ACTIVE.value, RunDir.DIAG.value)
        self.output_dir = os.path.join(save_root, action.action_output_dir)
        exp_dir = os.path.dirname(self.output_dir)
        exp_yml_paths = glob(os.path.join(exp_dir, "*.yml"))
        self.exp_yml_path = exp_yml_paths[0] if exp_yml_paths else None
        seq_dir = os.path.dirname(exp_dir)
        seq_yml_paths = glob(os.path.join(seq_dir, "*.yml"))
        self.seq_yml_path = seq_yml_paths[0] if seq_yml_paths else None
        self.files = action.files

    @abstractmethod
    def process(self) -> list[FileInfo]:
        """Run post-processing and return the updated file list.

        Returns:
            The new ``FileInfo`` list reflecting any files added, removed,
            or rewritten by the processor.
        """


class MetaProcessor(ABC):
    """Abstract base for in-place mutation of action/experiment/sequence metadata.

    Subclasses implement :meth:`process` to modify ``self.meta`` directly.

    Attributes:
        core: The owning runtime object (e.g. orchestrator or base server).
        meta: The metadata model to be mutated.
        meta_type: Lowercased class name of ``meta`` (e.g. ``"action"``).
        global_params: Orchestrator global parameters dict when ``core`` is an
            orchestrator, otherwise an empty dict.
    """

    def __init__(self, meta, core):
        """Capture the metadata target and surrounding runtime context.

        Args:
            meta: The metadata object that :meth:`process` will mutate.
            core: The runtime object owning the metadata; orchestrator
                instances contribute ``global_params``.
        """
        self.core = core
        self.meta = meta
        self.meta_type = meta.__class__.__name__.lower()
        self.global_params = (
            core.global_params if core.__class__.__name__.lower() == "orch" else {}
        )

    @abstractmethod
    def process(self) -> None:
        """Mutate ``self.meta`` in place."""
