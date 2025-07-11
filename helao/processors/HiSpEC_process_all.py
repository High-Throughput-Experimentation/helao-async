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
from helao.helpers.parquet import hlo_to_parquet
from helao.helpers.HiSpEC_calibrate_downsample_parquet import (
    fully_read_and_calibrate_parquet,
)
import tempfile
from pathlib import Path


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
                            cv_path=cvact.data_files[
                                0
                            ],  # .data_files is now a property func that evaluates at call time, calling it here will get the freshest path since hlo_to_parquet might take some time
                            spec_path=temp_file.name,
                            write_file=False,
                        ).sort_values(by="t (s)")
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
                    df.rename(columns={"J (A)": "J_A"}, inplace=True)
                    # reset the index
                    df.reset_index(drop=True, inplace=True)

                    non_WL_cols = ["t_s", "U_V", "J_A", "cycle", "direction"]
                    WL_map = {
                        col: f"WL_{i}"
                        for i, col in enumerate(
                            [x for x in df.columns if x not in non_WL_cols]
                        )
                    }

                    df.rename(columns=WL_map, inplace=True)
                    df.attrs["wl_dict"] = {
                        v: k for k, v in WL_map.items()
                    }  # Save inverse wl_dict for easy remapping
                    # write the dataframe to a parquet file
                    df.to_parquet(
                        new_file_path,
                        index=False,
                        partition_cols=["cycle", "direction"],
                    )

                    file_list = Path(new_file_path).glob("**/*.parquet")
                    for file in file_list:
                        new_file = copy(act_file)
                        new_file.file_type = "andor_spec_parquet__file"
                        relpath = (
                            Path(file)
                            .resolve()
                            .relative_to(Path(new_file_path).parent.resolve())
                        )
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
