from helao.helpers import logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

import os
from typing import List
from copy import copy
from helao.core.models.file import FileInfo
from helao.helpers.hlo_postprocessor import HloPostProcessor
from helao.helpers.read_hlo import HelaoData
from helao.helpers.parquet import read_hlo_header, read_hlo_data_chunks, hlo_to_parquet
from helao.helpers.HiSpEC_calibrate_downsample_parquet import fully_read_and_calibrate_parquet
import tempfile
from helao.helpers.read_hlo import read_hlo
from helao.helpers.parquet import read_hlo_header, read_hlo_data_chunks, hlo_to_parquet
from helao.helpers.HiSpEC_calibrate_downsample_parquet import fully_read_and_calibrate_parquet
import tempfile
import pandas as pd

class PostProcess(HloPostProcessor):

    def process(self) -> List[FileInfo]:
        processed_file_list = []
        for act_file in self.files:
            try:
                if act_file.file_type == "andor_helao__file":
                    file_path = os.path.join(self.output_dir, act_file.file_name)
                    hd=HelaoData(self.exp_yml_path)
                    cv_dir=hd.act[3].ymldir
                    for file in os.listdir(cv_dir):
                        if file.endswith(".hlo"):
                            cvpath=os.path.join(cv_dir, file)
                    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.csv') as temp_file:
                        hlo_to_parquet(file_path, temp_file.name, HiSpEC=True)
                        df=fully_read_and_calibrate_parquet(cv_path=cvpath, spec_path=temp_file.name, write_file=False).sort_values(by='t (s)')
                    action_comment = self.action.action_params.get("comment", "")
                    new_file_path = file_path.replace(".hlo", ".parquet")
                    if action_comment:
                        new_file_path = new_file_path.replace(".parquet", f"_{action_comment}.parquet")
                    df.to_parquet(new_file_path, index=False)
                    new_file = copy(act_file)
                    new_file.file_type = "parquet__file"
                    new_file.file_name = os.path.basename(new_file_path)
                    processed_file_list.append(new_file)
                    
            except Exception: 
                LOGGER.error(f"Error processing file: {act_file.file_name}", exc_info=True)
            processed_file_list.append(act_file)
        
        return processed_file_list
        