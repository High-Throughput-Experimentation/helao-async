"""In-memory port fakes for domain-adjacent unit tests (spec §10.2).

TEST-ONLY in P1a. Each fake logs a WARNING banner at construction so a
"green on fakes" run is visible in output; production composition (P1b)
raises on unwired ports and never defaults to these.
"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from helao.hexagon.domain.models import (
    Action,
    ActionServerModel,
    DataModel,
    ErrorCodes,
)

LOGGER = logging.getLogger(__name__)


def _banner(name: str) -> None:
    LOGGER.warning("FAKE PORT IN USE: %s (test-only, never production)", name)


class FakeClock:
    def __init__(self, fixed: Optional[datetime] = None, offset_s: float = 0.0):
        _banner("FakeClock")
        self._fixed = fixed
        self._offset = offset_s

    def now(self) -> datetime:
        return self._fixed if self._fixed is not None else datetime.now()

    def now_ns(self) -> int:
        if self._fixed is not None:
            return int(self._fixed.timestamp() * 1e9)
        return time.time_ns()

    def offset(self) -> float:
        return self._offset


class FakeTransport:
    """Records every dispatch; scripted responses/failures."""

    def __init__(
        self,
        respond_with: Optional[dict] = None,
        fail_with: Optional[ErrorCodes] = None,
    ):
        _banner("FakeTransport")
        self._respond_with = respond_with
        self._fail_with = fail_with
        self.dispatched: List[Tuple[str, dict]] = []
        self.private_calls: List[Tuple[str, str, dict]] = []
        self.probed: List[str] = []

    async def dispatch_action(
        self,
        action: Action,
        params: Optional[dict] = None,
        timeout: float = 60,
        retries: int = 5,
    ) -> Tuple[Optional[dict], ErrorCodes]:
        method = f"{action.action_server.server_name}/{action.action_name}"
        payload = dict(params or {})
        payload["action"] = action.as_dict()
        self.dispatched.append((method, payload))
        if self._fail_with is not None:
            return None, self._fail_with
        return self._respond_with or action.as_dict(), ErrorCodes.none

    async def dispatch_private(
        self,
        server_key: str,
        host: str,
        port: int,
        private_action: str,
        params_dict: Optional[dict] = None,
        json_dict: Optional[dict] = None,
        timeout: float = 60,
        retries: int = 5,
    ) -> Tuple[Optional[dict], ErrorCodes]:
        self.private_calls.append(
            (
                server_key,
                private_action,
                {**(params_dict or {}), **(json_dict or {})},
            )
        )
        if self._fail_with is not None:
            return None, self._fail_with
        return self._respond_with or {}, ErrorCodes.none

    async def check_endpoint(self, url: str, timeout: float = 3.0) -> bool:
        self.probed.append(url)
        return self._fail_with is None


class FakeArtifactStore:
    def __init__(self):
        _banner("FakeArtifactStore")
        self.writes: List[Tuple[str, object]] = []
        self.data_lines: List[Tuple[object, object]] = []
        self.moved: List[object] = []
        self.finished: List[object] = []

    async def write_act(self, action: Action) -> None:
        self.writes.append(("act", action))

    async def write_exp(self, experiment) -> None:
        self.writes.append(("exp", experiment))

    async def write_seq(self, sequence) -> None:
        self.writes.append(("seq", sequence))

    async def write_data_line(self, action, file_conn_key, payload) -> None:
        self.data_lines.append((file_conn_key, payload))

    async def close_streams(self, action) -> None:
        pass

    async def write_one_shot(
        self, action, output_str, file_type, filename, header
    ) -> Optional[str]:
        self.writes.append(("one_shot", filename))
        return filename

    async def finish(self, action) -> None:
        self.finished.append(action)

    async def move_dir(self, hobj) -> bool:
        self.moved.append(hobj)
        return True

    async def zip_dir(self, dir_path: Path) -> Path:
        return dir_path.with_suffix(".zip")


class FakeDataSink:
    """Thread-safe recorder for the DataSink surface (list.append is atomic)."""

    def __init__(self):
        _banner("FakeDataSink")
        self.enqueued: List[DataModel] = []
        self.files: List[Tuple[str, str]] = []
        self.samples: List[Tuple[str, list]] = []
        self.lbuf: dict = {}
        self.estopped = False

    async def enqueue_data(self, datamodel, action=None) -> None:
        self.enqueued.append(datamodel)

    def enqueue_data_nowait(self, datamodel, action=None) -> None:
        self.enqueued.append(datamodel)

    async def enqueue_data_dflt(self, datadict: dict) -> None:
        self.enqueued.append(DataModel(data={}, errors=[]))

    def get_realtime_nowait(self, epoch_ns=None, offset=None) -> int:
        return time.time_ns()

    async def finish_hlo_header(self, file_conn_keys=None, realtime=None) -> None:
        pass

    async def write_file(
        self,
        output_str,
        file_type,
        filename=None,
        file_group=None,
        header=None,
        sample_str=None,
        file_sample_label=None,
        json_data_keys=None,
        action=None,
    ):
        self.files.append((file_type, filename or ""))
        return filename

    def write_file_nowait(
        self,
        output_str,
        file_type,
        filename=None,
        file_group=None,
        header=None,
        sample_str=None,
        file_sample_label=None,
        json_data_keys=None,
        action=None,
    ):
        self.files.append((file_type, filename or ""))
        return filename

    async def track_file(self, file_type, file_path, samples, action=None) -> None:
        self.files.append((file_type, file_path))

    async def append_sample(self, samples, IO, action=None) -> None:
        self.samples.append((IO, list(samples)))

    async def split(self, uuid_list=None, new_fileconnparams=None) -> list:
        return []

    def set_estop(self, action=None) -> None:
        self.estopped = True

    async def put_lbuf(self, payload: dict) -> None:
        self.lbuf.update(payload)

    def put_lbuf_nowait(self, payload: dict) -> None:
        self.lbuf.update(payload)

    def get_lbuf(self, key: str) -> tuple:
        return (self.lbuf.get(key), time.time())


class FakeStatusPush:
    def __init__(self):
        _banner("FakeStatusPush")
        self.clients: List[Tuple[str, str, int]] = []
        self.sent: List[ActionServerModel] = []
        self.nonblocking: List[tuple] = []
        self.published: List[Tuple[str, dict]] = []

    async def attach_client(
        self, client_servkey, client_host, client_port, retry_limit: int = 5
    ) -> bool:
        self.clients.append((client_servkey, client_host, client_port))
        return True

    async def detach_client(self, client_servkey, client_host, client_port) -> None:
        self.clients.remove((client_servkey, client_host, client_port))

    async def send_status(self, asm, retries: int = 5) -> None:
        self.sent.append(asm)

    async def send_nonblocking_status(
        self,
        client_servkey,
        client_host,
        client_port,
        server_key,
        exec_id,
        act_uuid,
        status,
        retries: int = 3,
    ) -> None:
        self.nonblocking.append((server_key, exec_id, act_uuid, status))

    async def publish_status(self, payload: dict) -> None:
        self.published.append(("status", payload))

    async def publish_data(self, payload: dict) -> None:
        self.published.append(("data", payload))

    async def publish_live(self, payload: dict) -> None:
        self.published.append(("live", payload))


class FakeStatePersistence:
    def __init__(self):
        _banner("FakeStatePersistence")
        self._stored: Optional[dict] = None

    def export_queues(self, payload: dict, timestamp_pck: bool = False) -> Path:
        self._stored = payload
        return Path("STATES/queues.pck")

    def import_queues(self) -> Optional[dict]:
        payload, self._stored = self._stored, None  # consume-and-archive
        return payload
