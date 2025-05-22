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
from helao.helpers.helao_data import HelaoData
from helao.helpers.parquet import hlo_to_parquet, read_helao_metadata
from helao.helpers.HiSpEC_calibrate_downsample_parquet import (
    fully_read_and_calibrate_parquet,
)
import tempfile
from pathlib import Path
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pandas as pd
class PostProcess(HloPostProcessor):

    def process(self) -> List[FileInfo]:
        processed_file_list = []
        for act_file in self.files:
            try:
                if act_file.file_type == "andor_helao__file":
                    file_path = os.path.join(self.output_dir, act_file.file_name)
                    hd = HelaoData(self.exp_yml_path)
                    cvact = hd.act[3]
                    with tempfile.NamedTemporaryFile(
                        mode="w+", delete=False, suffix=".csv"
                    ) as temp_file:
                        hlo_to_parquet(file_path, temp_file.name, HiSpEC=True)
                        df = fully_read_and_calibrate_parquet(
                            cv_path=cvact.data_files[0],  # .data_files is now a property func that evaluates at call time, calling it here will get the freshest path since hlo_to_parquet might take some time
                            spec_path=temp_file.name,
                        write_file=False,
                        ).sort_values(by="t (s)")
                        hlo_meta = read_helao_metadata(temp_file.name)
                    action_comment = self.action.action_params.get("comment", "")
                    new_file_path = file_path.replace(".hlo", ".parquet")
                    if action_comment:
                        new_file_path = new_file_path.replace(
                            ".parquet", f"_{action_comment}.parquet"
                        )
                    # add copy the index and insert it into the first column
                    df.insert(0, "U_V", df.index.values)
                    # rename t (s) to t_s
                    df.rename(columns={"t (s)": "t_s"}, inplace=True)
                    # rename J(A) to J_A
                    df.rename(columns={"J(A)": "J_A"}, inplace=True)
                    #reset the index
                    df.reset_index(drop=True, inplace=True)
                    # temporarily extract the t_s, U_V, J_A, cycle and direction columns
                    df_non_WL = df[["t_s", "U_V", "J_A", "cycle", "direction"]]
                    # drop the t_s, U_V, J_A, cycle and direction columns from the original dataframe
                    df= df.drop(columns=["t_s", "U_V", "J_A", "cycle", "direction"])
                    
                    # make a dictionary of the column names with the keys being an iterator of the form WL_i
                    # and the values being the original column names
                    
                    wl_dict = {col: f"WL_{i}" for i, col in enumerate(df.columns)}

                    
                    # rename the columns in the dataframe
                    df.rename(columns=wl_dict, inplace=True)
                    df.attrs["wl_dict"] = wl_dict  # Save wl_dict in DataFrame attrs
                    # add the t_s, U_V, J_A, cycle and direction columns back to the dataframe
                    df = pd.concat([df_non_WL, df], axis=1)
                    # write the dataframe to a parquet file
                    df.to_parquet(new_file_path, index=False, partition_cols=["cycle", "direction"])
                    







                    # table = pa.Table.from_pandas(df)
                    # schema = table.schema
                    # existing_metadata = schema.metadata
                    # custom_metadata = json.dumps(hlo_meta).encode("utf8")
                    # metadata = {**{"helao_metadata": custom_metadata}, **existing_metadata}

                    # table = table.replace_schema_metadata(metadata)
                    # schema = table.schema
                    # pq.write_to_dataset(table, new_file_path, partition_cols=["cycle", "direction"], schema=schema)        
                    # glob through new file path to get all the parquet files to generate a list of paths

                    file_list=Path(new_file_path).glob('**/*.parquet')
                    for file in file_list:
                        new_file = copy(act_file)
                        new_file.file_type = "andor_spec_parquet__file"
                        relpath = Path(file).resolve().relative_to(Path(new_file_path).parent.resolve())
                        posixpath = str(relpath).replace("\\", "/")
                        new_file.file_name = posixpath
                        new_file.nosync = False
                        processed_file_list.append(new_file)

            except Exception:
                LOGGER.error(
                    f"Error processing file: {act_file.file_name}", exc_info=True
                )
            processed_file_list.append(act_file)

        return processed_file_list
