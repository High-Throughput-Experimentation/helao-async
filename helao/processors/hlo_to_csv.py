from helao.helpers import logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

from typing import List
from copy import copy
from helao.core.models.file import FileInfo
from helao.helpers.premodels import Action
from helao.helpers.hlo_postprocessor import HloPostProcessor

from helao.helpers.read_hlo import read_hlo
import pandas as pd

class PostProcess(HloPostProcessor):
    def __init__(self, action: Action):
        super().__init__(action)

    def process(self) -> List[FileInfo]:
        processed_file_list = []
        for act_file in self.files:
            try:
                if act_file.file_type == "helao__file":
                    file_path = str(self.output_dir.joinpath(act_file.file_name))
                    _, data = read_hlo(file_path)
                    df = pd.DataFrame(data)
                    df.to_csv(file_path.replace(".hlo", ".csv"), index=False)
                    new_file = copy(act_file)
                    new_file.file_type = "csv__file"
                    new_file.file_name = act_file.file_name.replace(".hlo", ".csv")
                    processed_file_list.append(new_file)
                    
            except Exception: 
                LOGGER.error(f"Error processing file: {act_file.file_name}", exc_info=True)
            processed_file_list.append(act_file)
        
        return processed_file_list
        