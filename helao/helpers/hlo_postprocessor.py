import os
from typing import List
from glob import glob
from abc import ABC, abstractmethod
from helao.core.models.file import FileInfo
from helao.helpers.premodels import Action

class HloPostProcessor(ABC):
    
    def __init__(self, action: Action, save_root: str):
        self.action = action
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