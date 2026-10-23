"""JSON storage format: meta_io and hlo_data dual-format behaviour (spec §5)."""

import json
from pathlib import Path

import pytest

from helao.helpers.meta_io import (
    dumps_meta,
    meta_glob,
    read_meta,
    resolve_meta_path,
    write_meta,
)
from helao.helpers.premodels import Experiment
from helao.helpers.yml_tools import yml_dumps

META = {
    "file_type": "action",
    "action_uuid": "06a5a2d6-b26c-7673-8000-9f38fe556fd6",
    "action_timestamp": "2026-10-23 12:00:00.123456",
    "action_params": {"duration": 2.0, "label": "µ-cell"},
    "files": [{"file_name": "CA-0.0.0.0__0.jsonl", "file_type": "helao__file"}],
    "nested": {"none": None, "list": [1, 2.5, "x"]},
}


def test_read_meta_yml_and_json_are_equal(tmp_path):
    y = tmp_path / "260717.130509123456-act.yml"
    y.write_text(yml_dumps(META), encoding="utf-8")
    j = write_meta(tmp_path / "260718.130509123456-act.json", META)
    assert read_meta(y) == read_meta(j) == META
    assert read_meta(j.read_bytes(), name=j.name) == META
    assert read_meta(y.read_bytes(), name=y.name) == META


def test_read_meta_bytes_needs_a_name():
    with pytest.raises(ValueError):
        read_meta(b"{}")


def test_dumps_meta_is_pretty_utf8_with_trailing_newline():
    out = dumps_meta({"a": 1, "b": {"c": "µ"}})
    assert out == '{\n  "a": 1,\n  "b": {\n    "c": "µ"\n  }\n}\n'
    assert dumps_meta({"a": 1}, path="x-act.yml") == yml_dumps({"a": 1})


def test_dumps_meta_handles_numpy_nan_and_sets():
    import numpy as np

    out = json.loads(dumps_meta({"v": np.float64(1.5), "n": float("nan"), "s": {3, 1}}))
    assert out == {"v": 1.5, "n": None, "s": [1, 3]}


def test_int_keys_round_trip_through_the_model(tmp_path):
    exp = Experiment(experiment_name="x", process_order_groups={0: [0, 1], 1: [2]})
    p = write_meta(tmp_path / "260717.130509123456-exp.json", exp.clean_dict())
    raw = read_meta(p)
    assert raw["process_order_groups"] == {"0": [0, 1], "1": [2]}
    assert Experiment.model_validate(raw).process_order_groups == {0: [0, 1], 1: [2]}


def test_write_meta_rewrites_existing_yml(tmp_path):
    """In-flight rule: a record begun as YAML stays YAML, no .json twin."""
    y = tmp_path / "260717.130509123456-act.yml"
    y.write_text(yml_dumps({"action_status": ["active"]}), encoding="utf-8")
    written = write_meta(
        tmp_path / "260717.130509123456-act.json", {"action_status": ["finished"]}
    )
    assert written == y
    assert read_meta(y) == {"action_status": ["finished"]}
    assert not (tmp_path / "260717.130509123456-act.json").exists()
    assert resolve_meta_path(tmp_path / "260717.130509123456-act.json") == y


def test_write_meta_new_record_is_json_and_leaves_no_staging(tmp_path):
    written = write_meta(tmp_path / "d" / "260717.130509123456-seq.yml", {"a": 1})
    assert written.name == "260717.130509123456-seq.json"
    assert sorted(p.name for p in written.parent.iterdir()) == [written.name]


def test_meta_glob_mixed_suffixes_and_kinds(tmp_path):
    seq = tmp_path / "RUNS_FINISHED" / "25.28" / "0716" / "seq"
    exp = seq / "exp"
    act = exp / "act"
    act.mkdir(parents=True)
    (seq / "1-seq.yml").write_text("a: 1\n", encoding="utf-8")
    (exp / "2-exp.json").write_text("{}\n", encoding="utf-8")
    (exp / "0__u__T-prc.json").write_text("{}\n", encoding="utf-8")
    (act / "3-act.json").write_text("{}\n", encoding="utf-8")
    (act / "X__0.meta.json").write_text("{}\n", encoding="utf-8")
    assert meta_glob(seq, "seq") == [seq / "1-seq.yml"]
    assert meta_glob(seq, ("exp", "act"), "*") == []
    assert meta_glob(seq, ("exp", "act"), "*/*") == [exp / "2-exp.json"]
    assert meta_glob(seq, ("exp", "act"), "*/*/*") == [act / "3-act.json"]
    assert meta_glob(exp, "prc") == [exp / "0__u__T-prc.json"]
    assert meta_glob(tmp_path, "act", "**/*") == [act / "3-act.json"]
    wild = tmp_path / "RUNS_*" / "25.28" / "0716"
    assert meta_glob(wild, "seq", "*/*", wildcard_root=True) == [seq / "1-seq.yml"]


def test_meta_glob_escapes_root_by_default(tmp_path):
    """A label with [x] in a directory name must not hide its records."""
    d = tmp_path / "seq [x]"
    d.mkdir()
    (d / "1-act.json").write_text("{}\n", encoding="utf-8")
    assert meta_glob(d, "act") == [d / "1-act.json"]
    assert meta_glob(d, "act", wildcard_root=True) == []
