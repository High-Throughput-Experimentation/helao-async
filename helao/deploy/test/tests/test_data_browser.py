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


def test_read_json_columnar():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "out.json")
        with open(p, "w") as f:
            json.dump({"wl_nm": [400, 500], "abs": [0.1, 0.2], "note": "x"}, f)
        meta, data = readers.read_dataset(p, fmt="json")
        assert data == {"wl_nm": [400, 500], "abs": [0.1, 0.2]}, data
        assert meta == {"note": "x"}, meta
    print("test_read_json_columnar PASS")


def test_read_json_records():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "recs.json")
        with open(p, "w") as f:
            json.dump([{"a": 1, "b": 2}, {"a": 3, "b": 4}], f)
        _, data = readers.read_dataset(p, fmt="json")
        assert data == {"a": [1, 3], "b": [2, 4]}, data
    print("test_read_json_records PASS")


def test_read_parquet():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "pat.parquet")
        table = pa.table({"q": [1.0, 2.0], "I": [10.0, 20.0]})
        pq.write_table(table, p)
        _, data = readers.read_dataset(p)
        assert data == {"q": [1.0, 2.0], "I": [10.0, 20.0]}, data
    print("test_read_parquet PASS")


def test_read_hlo_from_zip():
    with tempfile.TemporaryDirectory() as d:
        hlo = os.path.join(d, "cv_data.hlo")
        _write_hlo(hlo)
        zip_path = os.path.join(d, "seq.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(hlo, "exp/act/cv_data.hlo")
        loc = readers.make_zip_locator(zip_path, "exp/act/cv_data.hlo")
        _, data = readers.read_dataset(loc, fmt="hlo")
        assert data["t_s"] == [0.0, 1.0], data
    print("test_read_hlo_from_zip PASS")


if __name__ == "__main__":
    test_read_hlo_file()
    test_read_json_columnar()
    test_read_json_records()
    test_read_parquet()
    test_read_hlo_from_zip()
