from typing import List
from abc import ABC, abstractmethod
from helao.core.models.file import FileInfo
from helao.helpers.premodels import Action

class HloPostProcessor(ABC):
    
    def __init__(self, action: Action):
        self.action = action
        self.output_dir = action.action_output_dir
        self.files = action.files
    
    @abstractmethod
    def process(self) -> List[FileInfo]:
        """Return updated list of all action files, after post-processing."""