"""A corrected record, handed back and named in ``/finish_yml``, re-uploads.

The offline proof that ``set_plate_id record`` plus ``POST /finish_yml`` makes
the **current** syncer upload corrected bodies -- and only those. It runs the
real tool over a synthetic record, then drives a real sync driver built the
production way (``save_root`` is the single ``RUNS`` tree, not ``RUNS_ACTIVE``)
with a recording S3 stand-in, for both syncer classes.

Two facts it documents on purpose: ``finish_pending`` does **not** find a record
in ``RUNS_FINISHED`` (only ``/finish_yml`` does), and a re-sync must not mint a
second process uuid or a second raw-data key.
"""

import json
from pathlib import Path

import pytest

from helao.core.drivers.data import sync_driver as legacy_sync
from helao.core.models.helaodirs import HelaoDirs
from helao.core.tests.set_plate_id import main
from helao.core.tests.test_set_plate_id import (
    ACT_SAMPLE,
    ACT_STD,
    ACT_SAMPLE_MEMBER,
    ACT_STD_MEMBER,
    EXP_UUID,
    HLO_NAME,
    NEW,
    NEW_LABEL,
    OLD,
    PRC_SAMPLE,
    PRC_STD,
    SEQ_MEMBER,
    SEQ_UUID,
    _twin,
    build_record,
    set_api,
)
from helao.deploy.test.servers.action.sim_db_server import RecordingS3Client
from helao.helpers.run_state import _prg_is_complete
from helao.hexagon.adapters.native import sync_driver as native_sync
from helao.hexagon.tests.sync_fixtures import drain, teardown_driver

BUCKET = "test-bucket"


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.delenv("HELAO_CREDENTIALS", raising=False)
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)
    set_api(monkeypatch, {"plate_id": NEW, "serial_no": OLD})


def _body(s3: Path, key: str) -> dict:
    return json.loads((s3 / BUCKET / key).read_text())


def _keys(s3: Path, prefix: str) -> set:
    return {
        p.relative_to(s3 / BUCKET).as_posix()
        for p in (s3 / BUCKET).rglob("*")
        if p.is_file() and p.relative_to(s3 / BUCKET).as_posix().startswith(prefix)
    }


@pytest.mark.parametrize("mod", [legacy_sync, native_sync], ids=["core", "native"])
@pytest.mark.asyncio
async def test_handback_then_finish_yml_uploads_the_corrected_bodies(
    tmp_path, monkeypatch, mod
):
    z, _, _ = build_record(tmp_path)
    assert main(["record", str(z), "--old", str(OLD), "--new", str(NEW)]) == 0
    twin = _twin(tmp_path)
    seq_yml = twin / SEQ_MEMBER

    hd = HelaoDirs(
        root=tmp_path, save_root=tmp_path / "RUNS", process_root=tmp_path / "PROCESSES"
    )
    drv = mod.SyncDriver({"aws_bucket": BUCKET, "max_tasks": 1}, hd)
    s3 = tmp_path / "S3_SIM"
    drv.s3 = RecordingS3Client(s3)
    try:
        # The gap the handback leaves: the sweep only looks under RUNS.
        assert not await drv.finish_pending()
        assert drv.task_queue.qsize() == 0
        assert not _keys(s3, "")

        await drv.enqueue_yml(seq_yml, 2)  # what POST /finish_yml does
        await drain(drv, 180)
    finally:
        await teardown_driver(drv)

    # No duplicates: the same process uuids, and exactly the two hlo bodies.
    assert _keys(s3, "process/") == {
        f"process/{PRC_SAMPLE}.json",
        f"process/{PRC_STD}.json",
    }
    assert _keys(s3, "raw_data/") == {
        f"raw_data/{ACT_SAMPLE}/{HLO_NAME}.json",
        f"raw_data/{ACT_STD}/{HLO_NAME}.json",
    }

    assert _body(s3, f"sequence/{SEQ_UUID}.json")["sequence_params"]["plate_id"] == NEW
    process = _body(s3, f"process/{PRC_SAMPLE}.json")
    assert process["samples_in"][0]["global_label"] == NEW_LABEL
    action = _body(s3, f"action/{ACT_SAMPLE}.json")
    assert action["samples_in"][0]["plate_id"] == NEW
    experiment = _body(s3, f"experiment/{EXP_UUID}.json")
    assert experiment["process_list"] == [PRC_SAMPLE, PRC_STD]

    # Every record yml the syncer shipped is marked complete in place. Its own
    # {pidx}__{uuid}__{tech}-prc.yml files never get a .prg and are skipped.
    ymls = [
        p
        for p in twin.rglob("*.yml")
        if p.name.endswith(("-seq.yml", "-exp.yml", "-act.yml"))
    ]
    assert len(ymls) == 4
    assert all(_prg_is_complete(p.with_suffix(".prg")) for p in ymls)
    assert (twin / ACT_SAMPLE_MEMBER).is_file() and (twin / ACT_STD_MEMBER).is_file()
