from helao.helpers import helao_logging as logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

import os
from typing import List
from copy import copy
import pandas as pd
from helao.core.models.file import FileInfo
from helao.helpers.hlo_postprocessor import HloPostProcessor
from helao.helpers.read_hlo import read_hlo
from pathlib import Path


class PostProcess(HloPostProcessor):

    def process(self) -> List[FileInfo]:
        processed_file_list = []
        for act_file in self.files:
            try:
                if act_file.file_type in ["spec_r_helao__file", "spec_t_helao__file"]:
                    file_path = os.path.join(self.output_dir, act_file.file_name)
                    meta, data = read_hlo(file_path)
                    wl = [round(x, 3) for x in meta["optional"]["wl"]]
                    df = pd.DataFrame(data)

                    action_comment = self.action.action_params.get("comment", "")
                    new_file_path = file_path.replace(".hlo", ".parquet")
                    if action_comment:
                        new_file_path = new_file_path.replace(
                            ".parquet", f"_{action_comment}.parquet"
                        )
                    # add copy the index and insert it into the first column
                    # rename t (s) to t_s
                    df.insert(0, "t_s", df.epoch_s - df.epoch_s.min())
                    df.drop(["error_code"], axis="columns", inplace=True)
                    df.reset_index(drop=True, inplace=True)

                    non_WL_cols = ["t_s", "epoch_s", "peak_intensity"]
                    ch_cols = sorted([x for x in df.columns if x.startswith("ch_")])
                    df.rename({x: y for x, y in zip(ch_cols, wl)}, axis="columns", inplace=True)
                    melted_df = df.melt(id_vars=non_WL_cols, value_name="intensity")
                    melted_df.rename({"variable": "wl_nm"}, axis=1, inplace=True)
                    melted_df["wl_nm"] = melted_df["wl_nm"].astype(float)

                    smelted_df = melted_df.sort_values(["t_s", "wl_nm"])
                    # write the dataframe to a parquet file
                    smelted_df.to_parquet(new_file_path)

                    pfile = Path(new_file_path)
                    if not pfile.is_file():
                        continue
                    new_file = copy(act_file)
                    new_file.file_type = act_file.file_type.replace(
                        "_helao__file", "_parquet__file"
                    )
                    relpath = (
                        Path(pfile)
                        .resolve()
                        .relative_to(Path(new_file_path).parent.resolve())
                    )
                    posixpath = str(relpath).replace("\\", "/")
                    new_file.file_name = posixpath
                    new_file.nosync = False
                    new_file.data_keys = list(smelted_df.columns)
                    processed_file_list.append(new_file)

                    Path(file_path).unlink()
                else:
                    processed_file_list.append(act_file)

            except Exception:
                LOGGER.error(
                    f"Error processing file: {act_file.file_name}", exc_info=True
                )

        return processed_file_list
