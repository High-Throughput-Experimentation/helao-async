"""hte live paths on JSON-format records (JSON storage spec §3)."""

import os
from types import SimpleNamespace

import pandas as pd

from helao.core.models.file import FileInfo
from helao.deploy.hte.drivers.data.calc_driver import Calc
from helao.deploy.hte.processors import hlo_to_csv, spec_melt_wls
from helao.helpers.meta_io import dumps_meta, write_meta
from helao.helpers.to_json import hlo_json_dumps


def _pair(d, stem, header, rows):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.meta.json").write_text(dumps_meta(header), encoding="utf-8")
    (d / f"{stem}.jsonl").write_text(
        "".join(hlo_json_dumps(r) + "\n" for r in rows), encoding="utf-8"
    )


def _pp(module, tmp_path, file_info):
    pp = object.__new__(module.PostProcess)
    pp.files = [file_info]
    pp.output_dir = str(tmp_path)
    pp.action = SimpleNamespace(action_params={})
    return pp


def test_hlo_to_csv_converts_a_jsonl(tmp_path):
    _pair(
        tmp_path,
        "CA-0.0.0.0__0",
        {"column_headings": ["t_s"]},
        [{"t_s": 0.0}, {"t_s": 1.0}],
    )
    f = FileInfo(file_type="pstat_helao__file", file_name="CA-0.0.0.0__0.jsonl")
    out = _pp(hlo_to_csv, tmp_path, f).process()
    assert [x.file_name for x in out] == ["CA-0.0.0.0__0.csv", "CA-0.0.0.0__0.jsonl"]
    assert (tmp_path / "CA-0.0.0.0__0.csv").read_text(
        encoding="utf-8"
    ).splitlines() == [
        "t_s",
        "0.0",
        "1.0",
    ]


def test_spec_melt_writes_a_sibling_parquet_for_a_jsonl(tmp_path):
    row = {
        "epoch_s": 0.0,
        "error_code": 0,
        "peak_intensity": 1.0,
        "ch_0": 1.0,
        "ch_1": 2.0,
    }
    _pair(
        tmp_path,
        "S-0.0.0.0__0",
        {"optional": {"wl": [400.0, 500.0]}},
        [row, {**row, "epoch_s": 1.0}],
    )
    f = FileInfo(file_type="spec_r_helao__file", file_name="S-0.0.0.0__0.jsonl")
    _pp(spec_melt_wls, tmp_path, f).process()
    assert (tmp_path / "S-0.0.0.0__0.parquet").exists()
    assert len(pd.read_parquet(tmp_path / "S-0.0.0.0__0.parquet")) == 4
    # legacy parity: the source rows and their header are consumed together
    assert not (tmp_path / "S-0.0.0.0__0.jsonl").exists()
    assert not (tmp_path / "S-0.0.0.0__0.meta.json").exists()


def test_gather_seq_data_reads_json_records_and_pairs(tmp_path):
    seq = tmp_path / "RUNS" / "2026" / "1023" / "120000__s__l"
    exp = seq / "261023.120001__e"
    act = exp / "0__0__SPEC__acquire_spec"
    write_meta(seq / "261023.120000000000-seq.json", {"sequence_name": "s"})
    write_meta(exp / "261023.120001000000-exp.json", {"experiment_name": "e"})
    # A colocated process record must not be taken for the experiment record.
    write_meta(exp / "0__u__T-prc.json", {"process_uuid": "u"})
    write_meta(act / "261023.120002000000-act.json", {"action_name": "acquire_spec"})
    _pair(act, "S-0.0.0.0__0", {"optional": {"wl": [1.0]}}, [{"ch_0": 1.0}])
    calc = Calc(config={})
    (entry,) = calc.gather_seq_data(str(seq), "acquire_spec").values()
    assert entry["meta"] == {"optional": {"wl": [1.0]}}
    assert dict(entry["data"]) == {"ch_0": [1.0]}
    assert entry["actd"]["action_name"] == "acquire_spec"
    assert entry["expd"]["experiment_name"] == "e"
    assert list(calc.gather_seq_exps(str(seq), "*").values()) == [
        {"experiment_name": "e"}
    ]
    assert calc.get_seq_dict(str(seq)) == {"sequence_name": "s"}
