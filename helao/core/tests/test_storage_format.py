"""JSON storage format: meta_io and hlo_data dual-format behaviour (spec §5)."""

import json
import zipfile
from pathlib import Path

import orjson
import pytest

from helao.helpers.hlo_data import (
    hlo_to_parquet,
    read_helao_metadata,
    read_hlo,
    read_hlo_header,
    read_hlo_pair_bytes,
    read_hlo_via,
    resolve_data_file,
)

from helao.helpers.meta_io import (
    dumps_meta,
    meta_glob,
    read_meta,
    resolve_meta_path,
    write_meta,
)
from helao.helpers.premodels import Experiment
from helao.helpers.to_json import hlo_json_dumps
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


HEADER = {
    "hlo_version": "2026.10.23",
    "action_name": "CA",
    "column_headings": ["t_s", "v"],
    "optional": {"wl": [400.0, 500.0]},
    "epoch_ns": 1761220800000000000,
}
ROWS = [{"t_s": 0.0, "v": 1.0}, {"t_s": 0.1, "v": [2.0, 3.0]}]
DATA = {"t_s": [0.0, 0.1], "v": [1.0, 2.0, 3.0]}


def write_legacy_hlo(path: Path, header: dict, rows: list) -> Path:
    body = "".join(hlo_json_dumps(r) + "\n" for r in rows)
    path.write_text(yml_dumps(header) + "%%\n" + body, encoding="utf-8")
    return path


def write_pair(dirpath: Path, stem: str, header, rows: list) -> Path:
    """New-format pair; ``header=None`` writes a header-less file. Returns the .jsonl."""
    dirpath.mkdir(parents=True, exist_ok=True)
    if header:
        (dirpath / f"{stem}.meta.json").write_text(dumps_meta(header), encoding="utf-8")
    data = dirpath / f"{stem}.jsonl"
    data.write_text("".join(hlo_json_dumps(r) + "\n" for r in rows), encoding="utf-8")
    return data


def test_read_hlo_every_shape_returns_the_same_pair(tmp_path):
    legacy = write_legacy_hlo(tmp_path / "L__0.hlo", HEADER, ROWS)
    jsonl = write_pair(tmp_path, "N__0", HEADER, ROWS)
    s3 = tmp_path / "S__0.hlo.json"
    s3.write_text(json.dumps({"meta": HEADER, "data": DATA}), encoding="utf-8")
    expected = (HEADER, DATA)
    for p in (legacy, jsonl, tmp_path / "N__0.meta.json", s3):
        meta, data = read_hlo(p)
        assert (meta, dict(data)) == expected, p.name


def test_header_less_jsonl_reads_empty_meta(tmp_path):
    p = write_pair(tmp_path, "H__0", None, ROWS)
    meta, data = read_hlo(p)
    assert meta == {} and dict(data) == DATA


def test_header_without_rows_is_a_lost_artifact(tmp_path):
    (tmp_path / "X__0.meta.json").write_text(dumps_meta(HEADER), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        read_hlo(tmp_path / "X__0.meta.json")


def test_jsonl_first_line_is_never_a_header(tmp_path):
    """Review Focus 5: a non-object first row is a row, not YAML."""
    p = tmp_path / "R__0.jsonl"
    p.write_text('oops: 1\n{"a": 1}\n', encoding="utf-8")
    meta, data = read_hlo(p)
    assert meta == {} and dict(data) == {"a": [1]}


def test_keep_keys_filters_on_every_shape(tmp_path):
    """Mutation check: the old ``k in keep_keys or k not in omit_keys`` keeps ``v``."""
    legacy = write_legacy_hlo(tmp_path / "L__0.hlo", HEADER, ROWS)
    jsonl = write_pair(tmp_path, "N__0", HEADER, ROWS)
    for p in (legacy, jsonl):
        assert list(read_hlo(p, keep_keys=["t_s"])[1]) == ["t_s"]
        assert list(read_hlo(p, omit_keys=["t_s"])[1]) == ["v"]


@pytest.mark.parametrize(
    "present, name, expected",
    [
        ({"a/X__0.jsonl", "a/X__0.meta.json"}, "a/X__0.hlo.json", "a/X__0.jsonl"),
        ({"a/X__0.hlo"}, "a/X__0.hlo.json", "a/X__0.hlo"),
        ({"a/X__0.jsonl"}, "a/X__0.hlo", "a/X__0.jsonl"),
        # R-4a: a header request resolves to the rows, never to itself
        ({"a/X__0.jsonl", "a/X__0.meta.json"}, "a/X__0.meta.json", "a/X__0.jsonl"),
        # R-4a: both formats present -> the current one wins
        ({"a/X__0.hlo", "a/X__0.jsonl"}, "a/X__0.hlo", "a/X__0.jsonl"),
        ({"a/X__0.hlo", "a/X__0.jsonl"}, "a/X__0.hlo.json", "a/X__0.jsonl"),
        # R-4a: an S3-rebuilt tree holds only the .hlo.json
        ({"a/X__0.hlo.json"}, "a/X__0.hlo.json", "a/X__0.hlo.json"),
        ({"a/notes.csv"}, "a/notes.csv", "a/notes.csv"),
        (set(), "a/X__0.hlo.json", None),
    ],
)
def test_resolve_data_file(present, name, expected, tmp_path):
    assert resolve_data_file(present, name) == expected
    assert resolve_data_file(present.__contains__, name) == expected
    for rel in present:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x", encoding="utf-8")
    assert resolve_data_file(tmp_path, name) == expected


def test_read_hlo_via_a_zip_reads_the_pair_by_its_s3_name(tmp_path):
    write_pair(tmp_path / "act", "N__0", HEADER, ROWS)
    write_legacy_hlo(tmp_path / "act" / "L__0.hlo", HEADER, ROWS)
    zp = tmp_path / "seq.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        for f in (tmp_path / "act").iterdir():
            zf.write(f, f"exp/act/{f.name}")
    with zipfile.ZipFile(zp) as zf:
        names = set(zf.namelist())
        for logical in ("exp/act/N__0.hlo.json", "exp/act/L__0.hlo.json"):
            meta, data = read_hlo_via(names, zf.read, logical)
            assert (meta, dict(data)) == (HEADER, DATA), logical
        with pytest.raises(FileNotFoundError):
            read_hlo_via(names, zf.read, "exp/act/missing__0.hlo.json")


def test_read_hlo_via_where_none_probes_the_getter(tmp_path):
    """R-13: no ``where``; FileNotFoundError/KeyError from the getter mean absent."""
    write_pair(tmp_path / "act", "N__0", HEADER, ROWS)
    zp = tmp_path / "seq.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        for f in (tmp_path / "act").iterdir():
            zf.write(f, f"act/{f.name}")
    with zipfile.ZipFile(zp) as zf:
        meta, data = read_hlo_via(None, zf.read, "act/N__0.hlo.json")
        assert (meta, dict(data)) == (HEADER, DATA)
        with pytest.raises(FileNotFoundError):
            read_hlo_via(None, zf.read, "act/missing__0.hlo.json")
    blobs = {
        "act/N__0.meta.json": dumps_meta(HEADER).encode(),
        "act/N__0.jsonl": b'{"t_s": 0.0, "v": 1.0}\n{"t_s": 0.1, "v": [2.0, 3.0]}\n',
    }
    meta, data = read_hlo_via(None, blobs.__getitem__, "act/N__0.hlo.json")
    assert (meta, dict(data)) == (HEADER, DATA)
    with pytest.raises(FileNotFoundError):
        read_hlo_via(None, blobs.__getitem__, "act/nope__0.hlo.json")


def test_read_hlo_pair_bytes_header_optional():
    rows = b'{"a": 1}\n{"a": 2}\n'
    assert read_hlo_pair_bytes(None, rows)[0] == {}
    assert dict(read_hlo_pair_bytes(orjson.dumps(HEADER), rows)[1]) == {"a": [1, 2]}


def test_header_and_parquet_from_a_pair(tmp_path):
    jsonl = write_pair(tmp_path, "P__0", HEADER, ROWS[:1] * 3)
    assert read_hlo_header(jsonl) == (HEADER, 0)
    assert read_hlo_header(tmp_path / "P__0.meta.json") == (HEADER, 0)
    out = tmp_path / "P__0.parquet"
    hlo_to_parquet(str(tmp_path / "P__0.meta.json"), str(out), chunk_size=2)
    assert read_helao_metadata(str(out)) == HEADER["optional"]
