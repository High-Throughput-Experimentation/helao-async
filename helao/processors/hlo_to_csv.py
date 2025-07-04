from helao.helpers import helao_logging as logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

import os
from typing import List
from copy import copy
from helao.core.models.file import FileInfo
from helao.helpers.hlo_postprocessor import HloPostProcessor

from helao.helpers.read_hlo import read_hlo
import pandas as pd

class PostProcess(HloPostProcessor):

    def process(self) -> List[FileInfo]:
        processed_file_list = []
        for act_file in self.files:
            try:
                if act_file.file_type == "helao__file":
                    file_path = os.path.join(self.output_dir, act_file.file_name)
                    _, data = read_hlo(file_path)
                    df = pd.DataFrame(data)
                    action_comment = self.action.action_params.get("comment", "")
                    new_file_path = file_path.replace(".hlo", ".csv")
                    if action_comment:
                        new_file_path = new_file_path.replace(".csv", f"_{action_comment}.csv")
                    df.to_csv(new_file_path, index=False)
                    new_file = copy(act_file)
                    new_file.file_type = "csv__file"
                    new_file.file_name = os.path.basename(new_file_path)
                    processed_file_list.append(new_file)
                    
            except Exception: 
                LOGGER.error(f"Error processing file: {act_file.file_name}", exc_info=True)
            processed_file_list.append(act_file)
        
        return processed_file_list
        