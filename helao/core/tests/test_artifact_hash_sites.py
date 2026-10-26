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


def test_publish_outputs_writes_where_local_output_path_says(tmp_path):
    from helao.core.drivers.data.analysis_layout import (
        local_output_path,
        publish_outputs,
    )
    from helao.hexagon.tests.test_analysis_artifact import make_model

    model = make_model()
    asyncio.run(
        publish_outputs(model, {"e0": 1.0, "processed_Energy": [1]}, str(tmp_path))
    )
    paths = [local_output_path(o, str(tmp_path)) for o in model["outputs"]]
    assert paths and all(os.path.isfile(p) for p in paths)


def test_sync_process_hashes_prc_and_marks_repush(tmp_path, ledger):
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
            for _ in range(2):
                exp_prog = driver.reconcile_processes(driver.get_progress(exp_yml))
                # a write-off re-push: the process is owed to S3 again
                exp_prog.dict["process_s3"].clear()
                exp_prog.write_dict()
                await driver.sync_process(exp_prog, force=True)
        finally:
            await teardown_driver(driver)

    asyncio.run(_run())
    rows = [r for r in ledger() if r["kind"] == "prc"]
    assert [r["event"] for r in rows] == ["artifact_final", "artifact_rewritten"]
    assert rows[1]["reason"] == "process_repush"
