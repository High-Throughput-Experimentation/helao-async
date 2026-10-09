"""LocalLoader and HelaoLoader return the same types. No test here hits S3 or a DB."""

import io
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlmodel import create_engine

from helao.core.drivers.data.loaders import helao_loader
from helao.core.drivers.data.loaders.localfs import LocalLoader
from helao.core.drivers.data.loaders.model_base import HloPayload

TS = "20260925.094102000000"
HLO = "%s\n%%%%\n%s\n" % ("probe: 1", json.dumps({"v": [1.0, 2.0]}))
PRC_UUID = "0199a1b2-0000-7000-8000-000000000001"
ACT_UUID = "0199a1b2-0000-7000-8000-000000000002"


def _record(tmp_path: Path) -> Path:
    """One sequence holding an action with an .hlo and a process naming it."""
    day = tmp_path / "RUNS" / "2026" / "0925"
    seq_dir = day / "094102__seqA__lab"
    exp_dir = seq_dir / f"{TS}__expA"
    act_dir = exp_dir / "0__0__SIM__do_thing"
    act_dir.mkdir(parents=True)
    hlo_file = {"file_name": "d.hlo", "file_type": "x_helao__file", "data_keys": ["v"]}
    (act_dir / "d.hlo").write_text(HLO)
    (act_dir / f"{TS}-act.yml").write_text(
        f"action_name: do_thing\naction_uuid: {ACT_UUID}\n"
        f"action_timestamp: 2026-09-25 09:41:02\nfiles: {json.dumps([hlo_file])}\n"
    )
    (exp_dir / f"{TS}-exp.yml").write_text("experiment_name: expA\n")
    (seq_dir / f"{TS}-seq.yml").write_text("sequence_name: seqA\n")
    act_out = act_dir.relative_to(tmp_path / "RUNS").as_posix()
    prc = {
        "technique_name": "tech",
        "process_uuid": PRC_UUID,
        "dispatched_actions_abbr": [
            {"action_uuid": ACT_UUID, "action_output_dir": act_out}
        ],
        "files": [dict(hlo_file, action_uuid=ACT_UUID, run_use="data")],
    }
    (exp_dir / f"0__{PRC_UUID}__tech-prc.yml").write_text(json.dumps(prc))
    return seq_dir


def test_payload_is_a_dict_that_unpacks_as_meta_data():
    p = HloPayload({"a": 1}, {"v": [1]})
    meta, data = p
    assert (meta, data) == ({"a": 1}, {"v": [1]})
    assert p == {"meta": {"a": 1}, "data": {"v": [1]}}
    assert json.loads(json.dumps(p)) == {"meta": {"a": 1}, "data": {"v": [1]}}
    assert HloPayload() == {"meta": {}, "data": {}}


def test_local_action_hlo_and_dict_forms(tmp_path):
    loader = LocalLoader(str(_record(tmp_path)))
    act = loader.get_act(0)
    assert isinstance(act.hlo, HloPayload)
    assert act.hlo["data"]["v"] == [1.0, 2.0]
    _, data = act.read_hlo_file("d.hlo")
    assert data["v"] == [1.0, 2.0]
    assert isinstance(act.timestamp, datetime)
    raw = loader.get_act(0, hmod=False)
    assert isinstance(raw, dict) and raw["action_uuid"] == ACT_UUID


def test_local_process_reads_its_action_hlo(tmp_path):
    prc = LocalLoader(str(_record(tmp_path))).get_prc(0)
    assert prc.hlo["data"]["v"] == [1.0, 2.0]
    assert prc.hlo_file_tup[0] == "d.hlo"


def test_local_missing_keys_default_like_remote(tmp_path):
    seq = LocalLoader(str(_record(tmp_path))).get_seq(0)
    assert seq.uuid is None and seq.timestamp is None and seq.params == {}


def test_local_get_bytes_is_bytesio(tmp_path):
    loader = LocalLoader(str(_record(tmp_path)))
    out = loader.get_bytes(loader.get_act(0).yml_path, "d.hlo")
    assert isinstance(out, io.BytesIO) and out.read() == HLO.encode()


def test_remote_hlo_is_a_payload():
    body = json.dumps({"meta": {"probe": 1}, "data": {"v": [1.0]}}).encode()
    obj = SimpleNamespace(get=lambda: {"Body": io.BytesIO(body)})
    hl = object.__new__(helao_loader.HelaoLoader)
    hl.s3_cache, hl.cache_s3 = {}, False
    hl.res = SimpleNamespace(Object=lambda **_: obj)
    payload = hl.get_hlo("u", "d.hlo")
    assert isinstance(payload, HloPayload)
    assert payload["data"] == {"v": [1.0]}
    assert hl.get_hlo("u", "d.txt") == HloPayload()


def test_remote_timestamp_parses_to_datetime():
    assert helao_loader._as_datetime("2026-09-25T09:41:02") == datetime(
        2026, 9, 25, 9, 41, 2
    )
    assert helao_loader._as_datetime(None) is None


def test_sql_access_is_deprecated():
    hl = object.__new__(helao_loader.HelaoLoader)
    hl.engine = create_engine("sqlite://")
    with pytest.warns(DeprecationWarning, match="SQL"):
        hl.run_raw_query("select 1")
    hl.cache_sql = False
    hl._query = lambda _q: []
    with pytest.warns(DeprecationWarning, match="SQL"):
        assert hl.get_sql("action", "u") == {}


def test_local_process_hlo_from_synced_zip_with_hlo_json_name(tmp_path):
    """A process names the S3 ``.hlo.json``; a synced zip holds the raw ``.hlo``."""
    import shutil
    import zipfile

    seq_dir = _record(tmp_path)
    prc_yml = next(seq_dir.rglob("*-prc.yml"))
    prc = json.loads(prc_yml.read_text())
    prc["files"][0]["file_name"] = "d.hlo.json"
    prc_yml.write_text(json.dumps(prc))
    zip_path = seq_dir.parent / f"{seq_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in seq_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(seq_dir).as_posix())
    shutil.rmtree(seq_dir)
    loaded = LocalLoader(str(zip_path)).get_prc(0)
    assert loaded.hlo["data"]["v"] == [1.0, 2.0]


def test_remote_wrapper_timestamp_and_empty_hlo(monkeypatch):
    meta = {"action_name": "a", "action_timestamp": "2026-09-25T09:41:02", "files": []}
    monkeypatch.setattr(
        helao_loader, "LOADER", SimpleNamespace(get_json=lambda _t, _u: meta)
    )
    act = helao_loader.HelaoAction("u")
    assert act.timestamp == datetime(2026, 9, 25, 9, 41, 2)
    assert act.hlo == HloPayload()


def test_query_df_warning_points_at_the_caller(monkeypatch):
    import pandas as pd

    monkeypatch.setattr(
        helao_loader, "LOADER", SimpleNamespace(get_json=lambda _t, _u: {})
    )
    with pytest.warns(DeprecationWarning) as rec:
        helao_loader.HelaoAction("u", pd.DataFrame({"action_uuid": ["u"]}))
    assert rec[0].filename == __file__


def test_payload_copy_stays_a_payload():
    meta, data = HloPayload({"a": 1}, {}).copy()
    assert meta == {"a": 1}


def test_meta_dict_warns_once_at_the_caller(monkeypatch):
    hl = object.__new__(helao_loader.HelaoLoader)
    hl.cache_sql, hl._query = False, lambda _q: []
    monkeypatch.setattr(helao_loader, "LOADER", hl)
    act = object.__new__(helao_loader.HelaoAction)
    act.helao_type, act.uuid = "action", "u"
    with pytest.warns(DeprecationWarning) as rec:
        assert act._meta_dict == {}
    assert len(rec) == 1 and rec[0].filename == __file__
