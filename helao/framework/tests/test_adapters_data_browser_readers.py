"""Unit tests for the data_browser file readers adapter."""
import json
import os
import tempfile
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from helao.framework.adapters.data_browser import readers


def _write_hlo(path):
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
        assert data["t_s"] == [0.0, 1.0]
        assert data["Ewe_V"] == [0.1, 0.2]


def test_read_json_columnar():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "out.json")
        with open(p, "w") as f:
            json.dump({"wl_nm": [400, 500], "abs": [0.1, 0.2], "note": "x"}, f)
        meta, data = readers.read_dataset(p, fmt="json")
        assert data == {"wl_nm": [400, 500], "abs": [0.1, 0.2]}
        assert meta == {"note": "x"}


def test_read_json_records():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "recs.json")
        with open(p, "w") as f:
            json.dump([{"a": 1, "b": 2}, {"a": 3, "b": 4}], f)
        _, data = readers.read_dataset(p, fmt="json")
        assert data == {"a": [1, 3], "b": [2, 4]}


def test_read_parquet():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "pat.parquet")
        pq.write_table(pa.table({"q": [1.0, 2.0], "I": [10.0, 20.0]}), p)
        _, data = readers.read_dataset(p)
        assert data == {"q": [1.0, 2.0], "I": [10.0, 20.0]}


def test_read_hlo_from_zip():
    with tempfile.TemporaryDirectory() as d:
        hlo = os.path.join(d, "cv_data.hlo")
        _write_hlo(hlo)
        zip_path = os.path.join(d, "seq.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(hlo, "exp/act/cv_data.hlo")
        loc = readers.make_zip_locator(zip_path, "exp/act/cv_data.hlo")
        _, data = readers.read_dataset(loc, fmt="hlo")
        assert data["t_s"] == [0.0, 1.0]


def test_parse_locator_roundtrip():
    loc = readers.make_zip_locator("/a/b.zip", "exp/act/f.hlo")
    assert readers.parse_locator(loc) == ("zip", "/a/b.zip", "exp/act/f.hlo")
    assert readers.parse_locator("/a/b.hlo") == ("file", "/a/b.hlo")


def test_unsupported_format_raises():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.txt")
        with open(p, "w") as f:
            f.write("nope")
        with pytest.raises(ValueError):
            readers.read_dataset(p, fmt="txt")
