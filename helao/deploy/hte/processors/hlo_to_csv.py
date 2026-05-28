"""Post-processor that exports HLO action data as CSV.

For each ``*helao__file`` ending in ``.hlo``, reads the data,
optionally suffixes the filename with the action's ``comment``
parameter, and writes a sibling ``.csv`` file. The new file is
registered with its file type renamed from ``helao__file`` to
``csv__file``.
"""

import os
from typing import List
from copy import copy

import pandas as pd

from helao.core.models.file import FileInfo
from helao.helpers.processors import HloPostProcessor
from helao.helpers.hlo_data import read_hlo
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class PostProcess(HloPostProcessor):
    """Convert HLO data files to CSV and register the new files."""

    def process(self) -> List[FileInfo]:
        """Write a CSV copy of each ``.hlo`` data file in the action output.

        Returns:
            List[FileInfo]: Original files plus one ``*_csv__file``
            entry per converted HLO file.
        """
        processed_file_list = []
        for act_file in self.files:
            try:
                if act_file.file_type.endswith(
                    "helao__file"
                ) and act_file.file_name.endswith(".hlo"):
                    file_path = os.path.join(self.output_dir, act_file.file_name)
                    _, data = read_hlo(file_path)
                    df = pd.DataFrame(data)
                    action_comment = self.action.action_params.get("comment", "")
                    new_file_path = file_path.replace(".hlo", ".csv")
                    if action_comment:
                        new_file_path = new_file_path.replace(
                            ".csv", f"_{action_comment}.csv"
                        )
                    df.to_csv(new_file_path, index=False)
                    new_file = copy(act_file)
                    new_file.file_type = act_file.file_type.replace(
                        "helao__file", "csv__file"
                    )
                    new_file.file_name = os.path.basename(new_file_path)
                    processed_file_list.append(new_file)

            except Exception:
                LOGGER.error(
                    f"Error processing file: {act_file.file_name}", exc_info=True
                )
            processed_file_list.append(act_file)

        return processed_file_list
