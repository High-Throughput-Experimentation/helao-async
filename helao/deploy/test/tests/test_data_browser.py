"""Standalone tests for the data_browser package. No pytest; run with:

    PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao \
        python -m helao.deploy.test.tests.test_data_browser
"""
import json
import os
import tempfile
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from helao.core.servers.data_browser import readers
from helao.core.servers.data_browser import sources


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


def test_dir_walk_and_range():
    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, "RUNS_FINISHED")
        for ww, mmdd in [("26.20", "0515"), ("26.25", "0618")]:
            os.makedirs(os.path.join(base, ww, mmdd))
        dates = [ds for ds, _ in sources._list_day_dirs(base)]
        assert dates == ["26.20/0515", "26.25/0618"], dates
        assert sources._in_range("26.25/0618", "26.22", "26.30") is True
        assert sources._in_range("26.20/0515", "26.22", "26.30") is False
        assert sources._in_range("26.25/0618", None, None) is True
    print("test_dir_walk_and_range PASS")


def _make_finished_tree(root):
    """Create root/RUNS_FINISHED/26.25/0618/<seq>/<exp>/<act>/ with an .hlo + act.yml."""
    act_dir = os.path.join(
        root, "RUNS_FINISHED", "26.25", "0618",
        "141523__SDC_seq__lab1", "260618.141524__SDC_exp_CV",
        "1__0__sim__cv",
    )
    os.makedirs(act_dir)
    _write_hlo(os.path.join(act_dir, "cv_data.hlo"))
    with open(os.path.join(act_dir, "260618.141525-act.yml"), "w") as f:
        yaml.safe_dump({
            "technique_name": "CV",
            "run_type": "data",
            "samples_out": [{"global_label": "solid__lab1_1"}],
        }, f)


def test_runs_finished_index():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        idx = sources.RunsSourceIndex(d, "FINISHED")
        df = idx.index()
        assert list(df.columns) == sources.INDEX_COLUMNS, list(df.columns)
        assert len(df) == 1, df
        r = df.iloc[0]
        assert r["source"] == "RUNS_FINISHED"
        assert r["sequence"] == "SDC_seq"
        assert r["technique"] == "CV"
        assert r["sample"] == "solid__lab1_1"
        assert r["file_name"] == "cv_data.hlo"
        assert r["file_type"] == "hlo"
        assert r["available"] is True
        _, data = readers.read_dataset(r["locator"], r["file_type"])
        assert data["t_s"] == [0.0, 1.0]
    print("test_runs_finished_index PASS")


def _make_synced_zip(root):
    """Create root/RUNS_SYNCED/26.25/0618/<seq>.zip with act.yml + .hlo members."""
    day = os.path.join(root, "RUNS_SYNCED", "26.25", "0618")
    os.makedirs(day)
    with tempfile.TemporaryDirectory() as tmp:
        hlo = os.path.join(tmp, "cv_data.hlo")
        _write_hlo(hlo)
        actyml = os.path.join(tmp, "act.yml")
        with open(actyml, "w") as f:
            yaml.safe_dump({"technique_name": "CV",
                            "samples_out": [{"global_label": "solid__lab1_1"}]}, f)
        zpath = os.path.join(day, "141523__SDC_seq__lab1.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.write(actyml, "260618.141524__SDC_exp_CV/1__0__sim__cv/260618.141525-act.yml")
            zf.write(hlo, "260618.141524__SDC_exp_CV/1__0__sim__cv/cv_data.hlo")


def test_runs_synced_index():
    with tempfile.TemporaryDirectory() as d:
        _make_synced_zip(d)
        df = sources.RunsSourceIndex(d, "SYNCED").index()
        assert len(df) == 1, df
        r = df.iloc[0]
        assert r["source"] == "RUNS_SYNCED"
        assert r["sequence"] == "SDC_seq"
        assert r["technique"] == "CV"
        assert r["sample"] == "solid__lab1_1"
        assert r["file_name"] == "cv_data.hlo"
        assert r["locator"].startswith("zip::")
        _, data = readers.read_dataset(r["locator"], r["file_type"])
        assert data["Ewe_V"] == [0.1, 0.2]
    print("test_runs_synced_index PASS")


if __name__ == "__main__":
    test_read_hlo_file()
    test_read_json_columnar()
    test_read_json_records()
    test_read_parquet()
    test_read_hlo_from_zip()
    test_dir_walk_and_range()
    test_runs_finished_index()
    test_runs_synced_index()
