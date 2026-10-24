"""JSON storage format: meta_io and hlo_data dual-format behaviour (spec §5)."""

import io
import json
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import orjson
import pytest

from helao.core.drivers.data.process_locator import find_process_ymls, process_uuid_of
from helao.helpers.run_state import (
    identify_record,
    rebuild_from_tree,
    top_level_pair,
)
from helao.ui.shared import retire
from helao.core.drivers.data.loaders.localfs import LocalLoader
from helao.helpers.file_mapper import FileMapper
from helao.helpers.helao_data import HelaoData
from helao.ui.shared.data_browser.readers import make_zip_locator, read_dataset
from helao.ui.shared.data_browser.sources import RunsSourceIndex
from helao.helpers.hlo_data import (
    hlo_to_parquet,
    read_helao_metadata,
    read_hlo,
    read_hlo_header,
    read_hlo_pair_bytes,
    read_hlo_stream,
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
import helao.hexagon.adapters.native.sync_driver as sd
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
    # read_hlo drops the stream meta for .jsonl, so pin has_header=False directly
    meta, data = read_hlo_stream(io.BytesIO(p.read_bytes()), has_header=False)
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


def test_read_hlo_via_where_none_fetches_each_name_at_most_once():
    blobs = {
        "act/N__0.meta.json": dumps_meta(HEADER).encode(),
        "act/N__0.jsonl": b'{"t_s": 0.0, "v": 1.0}\n{"t_s": 0.1, "v": [2.0, 3.0]}\n',
    }
    calls: dict[str, int] = {}

    def get(n):
        calls[n] = calls.get(n, 0) + 1
        return blobs[n]

    read_hlo_via(None, get, "act/N__0.hlo.json")
    assert max(calls.values()) == 1, calls


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


U_SEQ = "00000000-0000-0000-0000-000000000001"
U_EXP = "00000000-0000-0000-0000-000000000002"
U_ACT = "00000000-0000-0000-0000-000000000003"


def _new_tree(root: Path) -> dict:
    """A one-seq/one-exp/one-act RUNS_FINISHED tree in the NEW format."""
    seq = root / "RUNS_FINISHED" / "25.28" / "0716" / "131415__GMTEST__golden"
    exp = seq / "250716.131420__TEST_exp"
    act = exp / "0__0__SIM__acquire_data"
    write_meta(
        seq / "250716.131415123456-seq.json",
        {
            "file_type": "sequence",
            "sequence_uuid": U_SEQ,
            "sequence_name": "GMTEST",
            "sequence_label": "golden",
            "sequence_timestamp": "2025-07-16 13:14:15.123456",
            "sequence_status": ["finished"],
            "sequence_params": {},
        },
    )
    write_meta(
        exp / "250716.131420123456-exp.json",
        {
            "file_type": "experiment",
            "experiment_uuid": U_EXP,
            "sequence_uuid": U_SEQ,
            "experiment_name": "TEST_exp",
            "experiment_timestamp": "2025-07-16 13:14:20.123456",
            "experiment_status": ["finished"],
            "experiment_params": {},
        },
    )
    write_meta(
        act / "250716.131421123456-act.json",
        {
            "file_type": "action",
            "action_uuid": U_ACT,
            "experiment_uuid": U_EXP,
            "sequence_uuid": U_SEQ,
            "action_name": "acquire_data",
            "action_timestamp": "2025-07-16 13:14:21.123456",
            "action_status": ["finished"],
            "action_params": {"label": "\u0189\u00b5"},
            "files": [
                {"file_name": "WsSim-0.0.0.0__0.jsonl", "file_type": "helao__file"}
            ],
        },
    )
    write_pair(act, "WsSim-0.0.0.0__0", HEADER, ROWS)
    return {"seq": seq, "exp": exp, "act": act}


def test_file_mapper_reads_pair_and_json_meta(tmp_path):
    t = _new_tree(tmp_path)
    fm = FileMapper(t["act"])
    rel = os.path.join(*t["act"].relative_to(tmp_path / "RUNS_FINISHED").parts)
    # the S3 name and the header name both resolve to the rows file's pair
    for name in ("WsSim-0.0.0.0__0.hlo.json", "WsSim-0.0.0.0__0.meta.json"):
        meta, data = fm.read_hlo(os.path.join(rel, name))
        assert (meta, dict(data)) == (HEADER, DATA)
    assert (
        fm.read_yml(os.path.join(rel, "250716.131421123456-act.json"))["action_uuid"]
        == U_ACT
    )


def test_file_mapper_reads_a_headerless_jsonl(tmp_path):
    act = tmp_path / "RUNS_FINISHED" / "25.28" / "0716" / "s" / "e" / "a"
    write_pair(act, "X__0", None, ROWS)
    fm = FileMapper(act)
    rel = os.path.join(*act.relative_to(tmp_path / "RUNS_FINISHED").parts)
    meta, data = fm.read_hlo(os.path.join(rel, "X__0.jsonl"))
    assert (meta, dict(data)) == ({}, DATA)


def test_file_mapper_reads_a_legacy_hlo_via_its_s3_name(tmp_path):
    act = tmp_path / "RUNS_FINISHED" / "25.28" / "0716" / "s" / "e" / "a"
    act.mkdir(parents=True)
    write_legacy_hlo(act / "X__0.hlo", HEADER, ROWS)
    fm = FileMapper(act)
    rel = os.path.join(*act.relative_to(tmp_path / "RUNS_FINISHED").parts)
    meta, data = fm.read_hlo(os.path.join(rel, "X__0.hlo.json"))
    assert (meta, dict(data)) == (HEADER, DATA)


def _zip_tree(tmp_path, t):
    zp = tmp_path / "RUNS_SYNCED" / "25.28" / "0716" / "131415__GMTEST__golden.zip"
    zp.parent.mkdir(parents=True)
    with zipfile.ZipFile(zp, "w") as zf:
        for f in t["seq"].rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(t["seq"]).as_posix())
    return zp


def test_helao_data_walks_a_json_tree(tmp_path):
    t = _new_tree(tmp_path)
    hd = HelaoData(str(t["seq"] / "250716.131415123456-seq.json"))
    assert hd.type == "seq" and hd.uuid == U_SEQ
    (exp,) = hd.exp
    (act,) = exp.act
    assert act.type == "act" and act.uuid == U_ACT
    assert [os.path.basename(p) for p in act.data_files] == ["WsSim-0.0.0.0__0.jsonl"]
    meta, data = act.read_data_file(act.data_files[0])
    assert (meta, dict(data)) == (HEADER, DATA)


def test_zipped_json_meta_keeps_non_ascii(tmp_path):
    """Review Focus 3: the legacy 0x89 repair must not touch a JSON member."""
    t = _new_tree(tmp_path)
    zp = _zip_tree(tmp_path, t)
    # 'U+0189' is C6 89 in UTF-8, so a blind 0x89 -> '%' swap corrupts it.
    act_member = (
        "250716.131420__TEST_exp/0__0__SIM__acquire_data/250716.131421123456-act.json"
    )
    ll = LocalLoader(data_path=str(zp))
    assert ll.get_yml(act_member)["action_params"]["label"] == "\u0189\u00b5"
    hd = HelaoData(str(zp))
    (act,) = hd.exp[0].act
    assert act.yml["action_params"]["label"] == "\u0189\u00b5"
    meta, data = act.read_hlo(act.data_files[0])
    assert (meta, dict(data)) == (HEADER, DATA)
    # FileMapper zip path too
    fm = FileMapper(tmp_path / "RUNS_FINISHED" / "25.28" / "0716")
    got = fm.read_yml("25.28/0716/131415__GMTEST__golden/" + act_member)
    assert got["action_params"]["label"] == "\u0189\u00b5"


def test_zipped_legacy_yml_keeps_the_0x89_repair(tmp_path):
    zp = tmp_path / "RUNS_SYNCED" / "25.28" / "0716" / "SEQ.zip"
    zp.parent.mkdir(parents=True)
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("e/a/x-act.yml", b"action_name: a\nnote: p\x89q\n")
    fm = FileMapper(tmp_path / "RUNS_FINISHED" / "25.28" / "0716")
    assert fm.read_yml("25.28/0716/SEQ/e/a/x-act.yml")["note"] == "p%q"


def test_local_loader_indexes_and_reads_a_json_tree(tmp_path):
    t = _new_tree(tmp_path)
    ll = LocalLoader(data_path=str(t["seq"]))
    assert (len(ll.sequences), len(ll.experiments), len(ll.actions)) == (1, 1, 1)
    meta, data = ll.get_act(0).hlo
    assert (meta, dict(data)) == (HEADER, DATA)


def test_data_browser_indexes_and_reads_a_pair(tmp_path):
    t = _new_tree(tmp_path)
    rows = RunsSourceIndex(tmp_path, "FINISHED").index()
    assert list(rows.file_name) == ["WsSim-0.0.0.0__0.jsonl"]
    assert list(rows.file_type) == ["jsonl"]
    meta, data = read_dataset(rows.locator.iloc[0])
    assert (meta, dict(data)) == (HEADER, DATA)
    zp = tmp_path / "z.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        for f in t["act"].iterdir():
            zf.write(f, f"a/{f.name}")
    meta, data = read_dataset(make_zip_locator(str(zp), "a/WsSim-0.0.0.0__0.jsonl"))
    assert (meta, dict(data)) == (HEADER, DATA)


def test_data_browser_lists_json_data_but_not_records_or_headers(tmp_path):
    t = _new_tree(tmp_path)
    (t["act"] / "foo.json").write_text('{"a": [1, 2]}', encoding="utf-8")
    rows = RunsSourceIndex(tmp_path, "FINISHED").index()
    assert sorted(rows.file_name) == ["WsSim-0.0.0.0__0.jsonl", "foo.json"]


def test_data_browser_process_resolves_s3_name_to_the_local_jsonl(tmp_path):
    from helao.ui.shared.data_browser.sources import DerivedSourceIndex

    t = _new_tree(tmp_path)
    write_meta(
        t["exp"] / "0__00000000-0000-0000-0000-0000000000aa__tech-prc.json",
        {
            "file_type": "process",
            "technique_name": "tech",
            "files": [
                {"file_name": "WsSim-0.0.0.0__0.hlo.json", "file_type": "helao__file"}
            ],
        },
    )
    rows = DerivedSourceIndex(tmp_path, "PROCESSES").index()
    assert len(rows) == 1
    r = rows.iloc[0]
    assert r["available"] and r["file_type"] == "jsonl"
    meta, data = read_dataset(r["locator"])
    assert (meta, dict(data)) == (HEADER, DATA)


def test_helao_data_finds_children_of_a_bracketed_runs_sequence(tmp_path):
    seq = tmp_path / "RUNS" / "25.28" / "0716" / "131415__GM[x]__golden"
    exp = seq / "250716.131420__TEST_exp"
    write_meta(
        seq / "250716.131415123456-seq.json",
        {"file_type": "sequence", "sequence_uuid": U_SEQ},
    )
    write_meta(
        exp / "250716.131420123456-exp.json",
        {"file_type": "experiment", "experiment_uuid": U_EXP},
    )
    hd = HelaoData(str(seq / "250716.131415123456-seq.json"))
    assert len(hd.exp) == 1


@pytest.mark.parametrize(
    "line, is_json, pair",
    [
        ("action_uuid: abc", False, ("action_uuid", "abc")),
        ('  "action_uuid": "abc",', True, ("action_uuid", "abc")),
        ('  "action_order": 3,', True, ("action_order", "3")),
        ('  "x": null', True, ("x", "None")),
        ('    "nested": "no",', True, (None, None)),
        ('  "params": {', True, (None, None)),
        ('  "list": [],', True, (None, None)),
        ("{", True, (None, None)),
    ],
)
def test_top_level_pair(line, is_json, pair):
    assert top_level_pair(line, is_json) == pair


def test_identify_record_reads_a_json_record_with_a_huge_head(tmp_path):
    """The uuid sits past the head window, as in a plate-sized -seq."""
    p = write_meta(
        tmp_path / "250716.131415123456-seq.json",
        {"sequence_params": {"big": ["x" * 80] * 2000}, "sequence_uuid": U_SEQ},
    )
    assert identify_record(p) == (U_SEQ, "sequence", None)


def test_rebuild_from_tree_counts_json_records(tmp_path):
    t = _new_tree(tmp_path)
    j = rebuild_from_tree(tmp_path / "RUNS_FINISHED", tmp_path / "STATES", "SYNC")
    assert sorted(r["kind"] for r in j.working_set().values()) == [
        "action",
        "experiment",
        "sequence",
    ]
    assert U_ACT in j.working_set()


def test_retire_locates_and_scans_json_records(tmp_path):
    t = _new_tree(tmp_path)
    (loc,) = retire.locate(str(tmp_path), U_SEQ)
    local, files = retire._scan_local([loc])
    assert files == 2 and local["EXPERIMENT"] == {U_EXP} and local["ACTION"] == {U_ACT}


def test_process_locator_finds_json_and_yml_processes(tmp_path):
    t = _new_tree(tmp_path)
    write_meta(t["exp"] / f"0__{U_EXP}__CV-prc.json", {"process_uuid": U_EXP})
    (t["exp"] / f"1__{U_ACT}__CA-prc.yml").write_text(
        "process_uuid: x\n", encoding="utf-8"
    )
    found = find_process_ymls(t["exp"] / "250716.131420123456-exp.json")
    assert [p.name for p in found] == [
        f"0__{U_EXP}__CV-prc.json",
        f"1__{U_ACT}__CA-prc.yml",
    ]
    assert [process_uuid_of(p) for p in found] == [U_EXP, U_ACT]


def test_progress_from_json_exp_has_int_group_keys(tmp_path):
    """Review Focus 4: JSON object keys are strings; .prg bookkeeping is int."""
    exp = write_meta(
        tmp_path
        / "RUNS"
        / "2026"
        / "1023"
        / "seq"
        / "exp"
        / "261023.120000000000-exp.json",
        {
            "experiment_uuid": U_EXP,
            "experiment_name": "e",
            "process_order_groups": {0: [0, 1], 1: [2]},
        },
    )
    assert sd.Progress(exp).dict["process_groups"] == {0: [0, 1], 1: [2]}
    assert sd.Progress(exp).dict["process_groups"] == {0: [0, 1], 1: [2]}  # from .prg


def test_helao_yml_walks_a_mixed_json_tree(tmp_path):
    seq = tmp_path / "RUNS" / "2026" / "1023" / "120000__s__l"
    s = seq / "261023.120000000000-seq.yml"
    s.parent.mkdir(parents=True)
    s.write_text("sequence_uuid: x\nsequence_status: [finished]\n", encoding="utf-8")
    e = write_meta(
        seq / "261023.120001__e" / "261023.120001000000-exp.json",
        {"experiment_status": ["finished"]},
    )
    a = write_meta(
        e.parent / "0__0__S__a" / "261023.120002000000-act.json",
        {"action_status": ["finished"]},
    )
    write_meta(e.parent / "0__u__T-prc.json", {"process_uuid": "u"})
    assert sd.HelaoYml(seq).target == s
    assert [c.target for c in sd.HelaoYml(s).children] == [e]
    assert [c.target for c in sd.HelaoYml(e).children] == [a]
    assert sd.HelaoYml(a).parent_yml == e
    assert sd.HelaoYml(e).parent_yml == s
    assert [p.name for p in sd.HelaoYml(e).process_ymls] == ["0__u__T-prc.json"]
    drv = sd.SyncDriver.__new__(sd.SyncDriver)
    drv.helaodirs = SimpleNamespace(save_root=tmp_path / "RUNS")  # type: ignore[assignment]
    assert [Path(p) for p in drv.list_pending()] == [s]
    assert [Path(p) for p in drv.list_pending_exps()] == [e]
    assert [Path(p) for p in drv.list_pending_acts()] == [a]


def _finish_pending_driver(pending, resets):
    drv = sd.SyncDriver.__new__(sd.SyncDriver)
    drv.list_pending = lambda *a, **k: pending  # type: ignore[method-assign]

    async def enqueue(path, rank=0):
        return None

    drv.enqueue_yml = enqueue  # type: ignore[method-assign]
    drv.reset_sync = lambda p: resets.append(p) or True  # type: ignore[method-assign]
    return drv


def test_finish_pending_does_not_reset_a_json_record(tmp_path):
    import asyncio

    seq = write_meta(
        tmp_path / "RUNS" / "2026" / "1023" / "s" / "261023.120000000000-seq.json",
        {"sequence_uuid": "x"},
    )
    resets = []
    asyncio.run(_finish_pending_driver([str(seq)], resets).finish_pending())
    assert resets == []


def test_finish_pending_still_resets_a_legacy_progress_sidecar(tmp_path):
    import asyncio

    seq = tmp_path / "RUNS_FINISHED" / "2026" / "1023" / "s" / "x-seq.yml"
    prog = tmp_path / "RUNS_SYNCED" / "2026" / "1023" / "s" / "x-seq.progress"
    prog.parent.mkdir(parents=True)
    prog.write_text("a: 1\n", encoding="utf-8")
    resets = []
    asyncio.run(_finish_pending_driver([str(seq)], resets).finish_pending())
    assert resets == [str(prog.parent)]


def test_register_present_files_takes_the_jsonl_not_its_header(tmp_path):
    from helao.hexagon.app.action_host import ActionHost
    from helao.helpers.premodels import Action

    host = ActionHost.__new__(ActionHost)
    host.server_key = "PSTAT"
    act_dir = tmp_path / "a"
    write_pair(act_dir, "CA-0.0.0.0__0", HEADER, ROWS)
    write_meta(act_dir / "260102.030405678901-act.json", {"action_name": "x"})
    action = Action(action_name="x")
    host._register_present_files(action, str(act_dir))
    assert [(f.file_name, f.file_type) for f in action.files] == [
        ("CA-0.0.0.0__0.jsonl", "pstat_helao__file")
    ]


def _assert_compact_rows(path: str, n: int) -> None:
    text = open(path, encoding="utf-8").read()
    assert text.endswith("\n")
    lines = text[:-1].split("\n")
    assert len(lines) == n
    for line in lines:
        assert line and line == line.strip()
        assert isinstance(json.loads(line), dict)
        assert line == hlo_json_dumps(json.loads(line))  # compact, no indent


def _assert_pretty_header(path: str) -> None:
    text = open(path, encoding="utf-8").read()
    assert text.endswith("}\n")
    assert '\n  "' in text  # 2-space indent
    assert text == dumps_meta(json.loads(text))


@pytest.mark.asyncio
async def test_real_writers_emit_compact_rows_and_a_pretty_header(tmp_path):
    import asyncio

    from helao.core.models.data import DataModel
    from helao.core.models.file import HloFileGroup
    from helao.hexagon.tests.native_fixtures import make_base, mk_active

    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, dflt = mk_active(base)
    task = asyncio.get_running_loop().create_task(active.log_data_task())
    await asyncio.sleep(0.05)
    for row in ROWS:
        await active.enqueue_data(DataModel(data={dflt: row}, errors=[]))
    await asyncio.sleep(0.2)
    task.cancel()
    await asyncio.sleep(0.05)
    await active.file_conn_dict[dflt].file.close()
    out_dir = Path(base.helaodirs.save_root) / str(active.action.action_output_dir)
    (streamed,) = sorted(out_dir.glob("*.jsonl"))
    _assert_compact_rows(str(streamed), len(ROWS))
    _assert_pretty_header(str(streamed)[: -len(".jsonl")] + ".meta.json")

    one_shot = await active.write_file(
        output_str="\n".join(hlo_json_dumps(r) for r in ROWS),
        file_type="x_helao__file",
        filename="one.jsonl",
        file_group=HloFileGroup.helao_files,
        header=HEADER,
    )
    assert one_shot is not None
    _assert_compact_rows(one_shot, len(ROWS))
    _assert_pretty_header(one_shot[: -len(".jsonl")] + ".meta.json")


@pytest.mark.asyncio
async def test_a_header_never_stands_alone(tmp_path):
    """A stream opened with a header and closed with no rows leaves both files."""
    from helao.core.models.file import HloFileGroup
    from helao.hexagon.tests.native_fixtures import make_base, mk_active

    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, dflt = mk_active(base)
    active.file_conn_dict[dflt].params.hloheader.epoch_ns = 1234567890
    await active.log_data_set_output_file(file_conn_key=dflt)
    await active.file_conn_dict[dflt].file.close()
    out_dir = Path(base.helaodirs.save_root) / str(active.action.action_output_dir)
    (data,) = sorted(out_dir.glob("*.jsonl"))
    assert data.with_name(data.name[: -len(".jsonl")] + ".meta.json").is_file()
    meta, rows = read_hlo(str(data))
    assert meta["epoch_ns"] == 1234567890 and not rows

    # one-shot with a header and an empty body: the .jsonl exists too
    path = await active.write_file(
        output_str="",
        file_type="x_helao__file",
        filename="empty.jsonl",
        file_group=HloFileGroup.helao_files,
        header={"k": 1},
    )
    assert path is not None and os.path.isfile(path)
    assert read_hlo(path) == ({"k": 1}, {})


def test_resolve_meta_path_rejects_a_suffixless_or_foreign_path(tmp_path):
    # with_suffix would otherwise turn "<ts>-act" into "<ts>.json"
    for bad in (tmp_path / "261023.120000123456-act", tmp_path / "x.hlo"):
        with pytest.raises(ValueError):
            resolve_meta_path(bad)
    ok = tmp_path / "261023.120000123456-act.json"
    assert resolve_meta_path(ok) == ok


def _fail_replace(monkeypatch, n):
    real, calls = os.replace, []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) <= n:
            raise PermissionError("[WinError 5] Access is denied")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr("helao.helpers.meta_io.time.sleep", lambda s: None)
    return calls


def test_write_meta_retries_a_reader_held_replace(tmp_path, monkeypatch):
    calls = _fail_replace(monkeypatch, 3)
    out = write_meta(tmp_path / "260101.000000000000-prc.json", {"a": 1})
    assert len(calls) == 4
    assert read_meta(out) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == [out.name]


def test_write_meta_gives_up_after_the_limit_and_cleans_staging(tmp_path, monkeypatch):
    calls = _fail_replace(monkeypatch, 10**6)
    with pytest.raises(PermissionError):
        write_meta(tmp_path / "260101.000000000000-prc.json", {"a": 1})
    assert 1 < len(calls) < 100
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [True, False])
async def test_move_dir_hands_off_the_record_the_writer_produced(
    tmp_path, monkeypatch, legacy
):
    """An in-flight stem with a .yml posts the .yml; a new record the .json."""
    from helao.core.tests.run_layout_fixtures import finished_action
    from helao.helpers import yml_tools

    hobj, base = finished_action(tmp_path)  # writes <ts>-act.yml
    act_dir = Path(str(base.helaodirs.save_root)) / hobj.get_action_dir()
    yml = next(act_dir.glob("*-act.yml"))
    if not legacy:
        yml.unlink()
        yml.with_suffix(".json").write_text("{}\n", encoding="utf-8")
    posted = []

    async def fake_finisher(path, sync_config=None, **kw):
        posted.append(path)

    monkeypatch.setattr(yml_tools, "yml_finisher", fake_finisher)
    await yml_tools.move_dir(hobj, base=base)
    assert [Path(p).suffix for p in posted] == [".yml" if legacy else ".json"]
