"""Standalone tests for the data_browser package. No pytest; run with:

    PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao \
        python -m helao.deploy.test.tests.test_data_browser
"""
import io
import json
import os
import tempfile
import zipfile

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from helao.core.servers.data_browser import readers


def _write_hlo(path):
    """Write a minimal HLO file (YAML header, %% marker, JSONL body)."""
    with open(path, "w") as f:
        f.write("hlo_version: 1.0\n")
        f.write("action_name: cv\n")
        f.write("column_headings: [t_s, Ewe_V]\n")
        f.write("%%\n")
        f.write(json.dumps({"t_s": 0.0, "Ewe_V": 0.1}) + "\n")
        f.write(json.dumps({"t_s": 1.0, "Ewe_V": 0.2}) + "\n")


def test_read_hlo_file():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cv_data.hlo")
        _write_hlo(p)
        meta, data = readers.read_dataset(p)
        assert data["t_s"] == [0.0, 1.0], data
        assert data["Ewe_V"] == [0.1, 0.2], data
    print("test_read_hlo_file PASS")


if __name__ == "__main__":
    test_read_hlo_file()
