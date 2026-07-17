"""RecordingS3Client contract + sim_db_server import sanity (Linux, no AWS)."""

import io
import json
from pathlib import Path


def test_recording_client_upload_fileobj(tmp_path):
    from helao.deploy.test.servers.action.sim_db_server import RecordingS3Client

    rec = RecordingS3Client(tmp_path / "S3_SIM")
    rec.upload_fileobj(io.BytesIO(b'{"a": 1}'), "helao-sim", "action/u1.json")
    stored = tmp_path / "S3_SIM" / "helao-sim" / "action" / "u1.json"
    assert stored.read_bytes() == b'{"a": 1}'
    entries = [
        json.loads(x)
        for x in (tmp_path / "S3_SIM" / "manifest.jsonl").read_text().splitlines()
    ]
    assert entries == [
        {
            "bucket": "helao-sim",
            "key": "action/u1.json",
            "mode": "fileobj",
            "gzip": False,
        }
    ]


def test_recording_client_upload_file_and_gzip_flag(tmp_path):
    from helao.deploy.test.servers.action.sim_db_server import RecordingS3Client

    src = tmp_path / "payload.hlo"
    src.write_text("data")
    rec = RecordingS3Client(tmp_path / "S3_SIM")
    rec.upload_file(str(src), "helao-sim", "raw_data/u1/payload.hlo.json.gz")
    stored = (
        tmp_path / "S3_SIM" / "helao-sim" / "raw_data" / "u1" / "payload.hlo.json.gz"
    )
    assert stored.read_text() == "data"
    entry = json.loads(
        (tmp_path / "S3_SIM" / "manifest.jsonl").read_text().splitlines()[0]
    )
    assert entry["mode"] == "file" and entry["gzip"] is True


def test_module_imports_and_exposes_makeapp():
    import helao.deploy.test.servers.action.sim_db_server as mod

    assert callable(mod.makeApp)
    assert issubclass(mod.SimHelaoSyncer, object)
