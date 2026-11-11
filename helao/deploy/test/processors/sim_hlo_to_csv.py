"""Test-deployment post-processor: HLO/JSONL action data to a sibling CSV.

Same contract as a production CSV exporter, held here so the framework tests and
the golden configs have a processor that does not depend on any instrument
deployment. Each ``*helao__file`` data file gets a ``.csv`` sibling, registered
with its file type renamed to ``csv__file``.
"""

import os
from copy import copy

import pandas as pd

from helao.core.models.file import FileInfo
from helao.hexagon.domain.naming import data_sibling
from helao.helpers import helao_logging as logging
from helao.helpers.hlo_data import read_hlo
from helao.helpers.processors import HloPostProcessor

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class PostProcess(HloPostProcessor):
    """Convert HLO/JSONL data files to CSV and register the new files."""

    def process(self) -> list[FileInfo]:
        out = []
        for act_file in self.files:
            try:
                if act_file.file_type.endswith(
                    "helao__file"
                ) and act_file.file_name.endswith((".hlo", ".jsonl")):
                    path = os.path.join(self.output_dir, act_file.file_name)
                    _, data = read_hlo(path)
                    new_path = data_sibling(path, ".csv")
                    comment = self.action.action_params.get("comment", "")
                    if comment:
                        new_path = new_path.replace(".csv", f"_{comment}.csv")
                    pd.DataFrame(data).to_csv(new_path, index=False)
                    new_file = copy(act_file)
                    new_file.file_type = act_file.file_type.replace(
                        "helao__file", "csv__file"
                    )
                    new_file.file_name = os.path.basename(new_path)
                    out.append(new_file)
            except Exception:
                LOGGER.error(
                    f"Error processing file: {act_file.file_name}", exc_info=True
                )
            out.append(act_file)
        return out
