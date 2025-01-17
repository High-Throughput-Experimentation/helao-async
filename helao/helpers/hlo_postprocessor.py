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
        self.exp_yml_path = glob(os.path.join(exp_dir, "*.yml"))[0]
        seq_dir = os.path.dirname(exp_dir)
        self.seq_yml_path = glob(os.path.join(seq_dir, "*.yml"))[0]
        self.files = action.files
    
    @abstractmethod
    def process(self) -> List[FileInfo]:
        """Return updated list of all action files, after post-processing."""