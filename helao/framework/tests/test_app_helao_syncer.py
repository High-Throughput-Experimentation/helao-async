"""SP-ORCH-5 follow-up: framework HelaoSyncer (Base-aware SyncDriver wiring).

Port of legacy helao.core.drivers.data.sync_driver.HelaoSyncer. Verifies it pulls
config from the server (with DB fallback) and constructs the framework sync ports the
base SyncDriver requires — FsSyncStorage + an S3 sink when AWS is configured else a
NoopCloudSink (so the syncer runs / unit-tests without S3). dbpack_server is intentionally
NOT switched to this yet (legacy seam kept until DB-server S3 bring-up).
"""

from helao.framework.app.sync_driver import HelaoSyncer, SyncDriver
from helao.framework.adapters.fs_sync_storage import FsSyncStorage
from helao.framework.adapters.noop_cloud_sink import NoopCloudSink


class _FakeBase:
    """Minimal Base stand-in: only the attrs HelaoSyncer reads."""

    def __init__(self, server_cfg=None, world_cfg=None, helaodirs="DIRS"):
        self.server_cfg = server_cfg or {}
        self.world_cfg = world_cfg or {}
        self.helaodirs = helaodirs


def test_helaosyncer_is_syncdriver_subclass():
    assert issubclass(HelaoSyncer, SyncDriver)


def test_helaosyncer_noop_sink_when_no_aws():
    base = _FakeBase(server_cfg={"params": {"max_tasks": 3}})
    syncer = HelaoSyncer(base)
    assert isinstance(syncer.sync_storage, FsSyncStorage)
    assert isinstance(syncer.cloud_sink, NoopCloudSink)
    assert syncer.config["max_tasks"] == 3
    assert syncer.helaodirs == "DIRS"
    assert syncer.base is base


def test_helaosyncer_borrows_db_params_when_no_local_aws():
    # Local server has no aws_config_path -> fall back to the DB server's params.
    base = _FakeBase(
        server_cfg={"params": {}},
        world_cfg={"servers": {"DB": {"params": {"max_tasks": 7, "aws_bucket": None}}}},
    )
    syncer = HelaoSyncer(base)
    assert syncer.config["max_tasks"] == 7  # picked up from DB block
    assert isinstance(syncer.cloud_sink, NoopCloudSink)  # still no AWS bucket/path


def test_helaosyncer_selects_s3_sink_when_aws_configured(monkeypatch):
    # When aws_bucket is set, the S3 sink is chosen. Patch S3CloudSink so the test
    # does not touch boto3/AWS.
    import helao.framework.adapters.s3_cloud_sink as s3mod

    built = {}

    class _FakeS3:
        def __init__(self, config, *a, **k):
            built["config"] = config

    monkeypatch.setattr(s3mod, "S3CloudSink", _FakeS3)
    base = _FakeBase(server_cfg={"params": {"aws_bucket": "helao.data"}})
    syncer = HelaoSyncer(base)
    assert isinstance(syncer.cloud_sink, _FakeS3)
    assert built["config"]["aws_bucket"] == "helao.data"
