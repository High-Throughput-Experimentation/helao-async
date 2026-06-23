from pathlib import Path

from helao.framework.ports.cloud_sink import CloudSink


class DummyCloudSink:
    """Minimal structural implementation of every CloudSink method."""

    async def upload_bytes(
        self,
        data: bytes,
        key: str,
        content_type: str = "application/json",
        compress: bool = False,
    ) -> bool:
        return True

    async def upload_file(self, local_path: Path, key: str) -> bool:
        return True

    def key_exists(self, key: str) -> bool:
        return False

    async def register_api(
        self, req_model: dict, meta_type: str, retries: int = 5
    ) -> bool:
        return True


class PartialCloudSink:
    """Missing ``register_api`` -- must NOT satisfy the protocol."""

    async def upload_bytes(self, data, key, content_type="application/json", compress=False):
        return True

    async def upload_file(self, local_path, key):
        return True

    def key_exists(self, key):
        return False

    # register_api(...) intentionally omitted


def test_dummy_satisfies_protocol():
    sink: CloudSink = DummyCloudSink()
    assert isinstance(sink, CloudSink)


def test_partial_implementation_is_not_an_instance():
    assert not isinstance(PartialCloudSink(), CloudSink)
