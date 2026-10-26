"""Artefact hashes at the finalization points (spec §5)."""

import asyncio
import hashlib
import json
import logging
import os
from types import SimpleNamespace

import pytest

from helao.core.models.hlostatus import HloStatus
from helao.helpers import helao_logging
from helao.helpers.log_jsonl import JsonlSinkHandler


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    h = JsonlSinkHandler("SRV", tmp_path / "LOGS")
    lg = logging.getLogger("t_sites")
    lg.handlers[:] = [h]
    lg.setLevel(10)
    lg.propagate = False
    monkeypatch.setattr(helao_logging, "LOGGER", lg)

    def rows():
        h.flush()
        p = tmp_path / "LOGS" / "artifacts_SRV.jsonl"
        return (
            [json.loads(x) for x in p.read_bytes().splitlines()] if p.exists() else []
        )

    yield rows
    h.close()


def _writer(tmp_path):
    from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter

    async def atomic(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    base = SimpleNamespace(
        helaodirs=SimpleNamespace(save_root=str(tmp_path / "RUNS")),
        _write_meta_atomic=atomic,
    )
    return NativeMetaFileWriter(base)


def _action(status, files):
    from helao.hexagon.tests.native_fixtures import mk_action

    a = mk_action(save_act=True)
    a.action_status = status
    a.files = files
    return a


def _act_dir(tmp_path, a):
    d = tmp_path / "RUNS" / str(a.action_output_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_finished_action_hashes_record_and_files(tmp_path, ledger):
    from helao.core.models.file import FileInfo

    a = _action([HloStatus.finished], [FileInfo(file_name="CA-0__0.jsonl")])
    d = _act_dir(tmp_path, a)
    (d / "CA-0__0.jsonl").write_bytes(b"1\n2\n")
    (d / "CA-0__0.meta.json").write_bytes(b"{}")
    asyncio.run(_writer(tmp_path).write_act(a))
    rows = ledger()
    assert sorted(r["kind"] for r in rows) == ["act", "data", "data"]
    (data,) = [r for r in rows if r["path"].endswith("CA-0__0.jsonl")]
    assert data["sha256"] == hashlib.sha256(b"1\n2\n").hexdigest()
    assert any(r["path"].endswith("CA-0__0.meta.json") for r in rows)
    assert all(r["event"] == "artifact_final" for r in rows)


def test_active_action_write_is_not_hashed(tmp_path, ledger):
    a = _action([HloStatus.active], [])
    _act_dir(tmp_path, a)
    asyncio.run(_writer(tmp_path).write_act(a))
    assert ledger() == []


def test_reason_logs_rewritten(tmp_path, ledger):
    a = _action([HloStatus.errored], [])
    _act_dir(tmp_path, a)
    asyncio.run(_writer(tmp_path).write_act(a, reason="reconcile_interrupted"))
    (r,) = ledger()
    assert (r["event"], r["reason"]) == ("artifact_rewritten", "reconcile_interrupted")


def test_local_output_path(tmp_path):
    from helao.core.drivers.data.analysis_layout import local_output_path

    out = {"analysis_output_path": {"key": "analysis/abc/out_1.json"}}
    assert local_output_path(out, str(tmp_path)) == os.path.join(
        str(tmp_path), "out_1.json"
    )


def _failures(tmp_path):
    return [
        x
        for f in (tmp_path / "LOGS").glob("*.jsonl")
        for x in f.read_text(encoding="utf-8").splitlines()
        if "artifact_hash_failed" in x
    ]


def test_publish_outputs_writes_where_local_output_path_says(tmp_path, ledger):
    from helao.core.drivers.data.analysis_layout import (
        local_output_path,
        publish_outputs,
        write_model_json,
    )
    from helao.hexagon.tests.test_analysis_artifact import make_model

    model = make_model()
    write_model_json(str(tmp_path), model["analysis_uuid"], model)
    asyncio.run(
        publish_outputs(model, {"e0": 1.0, "processed_Energy": [1]}, str(tmp_path))
    )
    paths = [local_output_path(o, str(tmp_path)) for o in model["outputs"]]
    assert paths and all(os.path.isfile(p) for p in paths)
    rows = ledger()
    assert sorted(r["path"] for r in rows if r["kind"] == "output") == sorted(paths)
    (ana,) = [r for r in rows if r["kind"] == "ana"]
    assert ana["path"].endswith(f"{model['analysis_uuid']}-ana.json")
    assert not _failures(tmp_path)


def test_publish_outputs_hashes_ana_and_outputs_even_if_upload_raises(tmp_path, ledger):
    from helao.core.drivers.data.analysis_layout import (
        publish_outputs,
        write_model_json,
    )
    from helao.hexagon.tests.test_analysis_artifact import make_model

    model = make_model()
    write_model_json(str(tmp_path), model["analysis_uuid"], model)

    async def boom(msg, target, compress=False):
        raise BaseException("upload died")

    with pytest.raises(BaseException, match="upload died"):
        asyncio.run(
            publish_outputs(
                model, {"e0": 1.0, "processed_Energy": [1]}, str(tmp_path), boom
            )
        )
    rows = ledger()
    assert [r["kind"] for r in rows if r["kind"] == "ana"] == ["ana"]
    assert (
        os.path.basename([r["path"] for r in rows if r["kind"] == "ana"][0])
        == f"{model['analysis_uuid']}-ana.json"
    )


def _sync_prc_passes(tmp_path, between, passes=2, rename_to_yml=False):
    """Run sync_process ``passes`` times; ``between(i, prc_path)`` runs after pass i."""
    import glob

    from helao.core.models.run_dir import RunDir
    from helao.hexagon.adapters.native.sync_driver import SyncDriver
    from helao.hexagon.tests.sync_fixtures import (
        make_action,
        make_exp_tree,
        make_sync_driver,
        mk_uuid,
        teardown_driver,
    )

    exp_yml = make_exp_tree(
        tmp_path, RunDir.FINISHED.value, mk_uuid(1001), process_order_groups={0: [0]}
    )
    make_action(exp_yml, 0, process_finish=True)

    async def _run():
        driver = make_sync_driver(tmp_path, SyncDriver)
        try:
            for i in range(passes):
                exp_prog = driver.reconcile_processes(driver.get_progress(exp_yml))
                # a write-off re-push / S3 retry: the process is owed to S3 again
                exp_prog.dict["process_s3"].clear()
                exp_prog.write_dict()
                await driver.sync_process(exp_prog, force=True)
                (prc,) = glob.glob(str(tmp_path / "**" / "*-prc.*"), recursive=True)
                between(i, prc)
        finally:
            await teardown_driver(driver)

    asyncio.run(_run())


def test_sync_process_hashes_prc_first_write_then_only_real_changes(tmp_path, ledger):
    def between(i, prc):
        if i == 1:  # stale bytes on disk: the next pass genuinely rewrites
            with open(prc, "a", encoding="utf-8") as f:
                f.write("# stale\n")

    _sync_prc_passes(tmp_path, between, passes=3)
    rows = [r for r in ledger() if r["kind"] == "prc"]
    # pass 0 first write; pass 1 identical -> nothing; pass 2 bytes differ -> rewritten
    assert [r["event"] for r in rows] == ["artifact_final", "artifact_rewritten"]
    assert rows[0].get("reason") is None
    assert rows[1]["reason"] == "process_repush"


def test_sync_process_rewrites_legacy_prc_yml_and_hashes_the_yml(tmp_path, ledger):
    def between(i, prc):
        if i == 0:  # a pre-JSON-storage record: the prc on disk is YAML
            os.rename(prc, prc[: -len(".json")] + ".yml")
            with open(prc[: -len(".json")] + ".yml", "a", encoding="utf-8") as f:
                f.write("# stale\n")

    _sync_prc_passes(tmp_path, between, passes=2)
    rows = [r for r in ledger() if r["kind"] == "prc"]
    assert [r["event"] for r in rows] == ["artifact_final", "artifact_rewritten"]
    assert rows[1]["path"].endswith("-prc.yml")
    assert rows[1]["reason"] == "process_repush"
    assert not _failures(tmp_path)


def _exp_seq():
    from helao.helpers.premodels import Experiment, Sequence

    seq = Sequence(sequence_name="S")
    seq.init_seq(time_offset=0)
    exp = Experiment(experiment_name="E")
    exp.__dict__.update(
        {k: v for k, v in seq.__dict__.items() if k.startswith("sequence_")}
    )
    exp.init_exp(time_offset=0)
    return exp, seq


def test_exp_hash_only_when_terminal(tmp_path, ledger):
    exp, _ = _exp_seq()
    w = _writer(tmp_path)
    exp.experiment_status = [HloStatus.active]
    asyncio.run(w.write_exp(exp))
    assert ledger() == []
    exp.experiment_status = [HloStatus.finished]
    asyncio.run(w.write_exp(exp))
    (r,) = ledger()
    assert (r["kind"], r["event"]) == ("exp", "artifact_final")
    assert r["path"].endswith("-exp.json")


def test_seq_hash_only_when_terminal_and_reason_rewrites(tmp_path, ledger):
    _, seq = _exp_seq()
    w = _writer(tmp_path)
    seq.sequence_status = [HloStatus.active]
    asyncio.run(w.write_seq(seq, reason="x"))
    assert ledger() == []
    seq.sequence_status = [HloStatus.finished]
    asyncio.run(w.write_seq(seq, reason="x"))
    (r,) = ledger()
    assert (r["kind"], r["event"], r["reason"]) == ("seq", "artifact_rewritten", "x")


def test_data_files_hashed_even_when_save_act_false(tmp_path, ledger):
    from helao.core.models.file import FileInfo

    a = _action([HloStatus.finished], [FileInfo(file_name="CA-0__0.jsonl")])
    a.save_act = False
    d = _act_dir(tmp_path, a)
    (d / "CA-0__0.jsonl").write_bytes(b"1\n")
    asyncio.run(_writer(tmp_path).write_act(a))
    rows = ledger()
    assert [r["kind"] for r in rows] == ["data"]
    assert rows[0]["path"].endswith("CA-0__0.jsonl")


def test_micro_orch_hashes_terminal_exp_and_seq(tmp_path, ledger):
    from helao.core.runners.micro_orch import MicroOrch

    orch = MicroOrch(
        server_key="micro",
        host="127.0.0.1",
        port=9999,
        world_cfg={"root": str(tmp_path / "root"), "servers": {}},
    )
    exp, seq = _exp_seq()

    async def go():
        exp.experiment_status = [HloStatus.active]
        seq.sequence_status = [HloStatus.active]
        await orch._write_exp(exp)
        await orch._write_seq(seq)
        assert ledger() == []
        exp.experiment_status = [HloStatus.finished]
        seq.sequence_status = [HloStatus.finished]
        await orch._write_exp(exp)
        await orch._write_seq(seq)

    asyncio.run(go())
    assert sorted(r["kind"] for r in ledger()) == ["exp", "seq"]


def test_is_terminal():
    from helao.core.models.hlostatus import is_terminal

    assert is_terminal([HloStatus.active, HloStatus.finished])
    assert not is_terminal([HloStatus.active])
    assert not is_terminal([]) and not is_terminal(None)
