"""Process-wide WebSocket ingest for the Reflex UI stack.

The Bokeh visualizers open one :class:`~helao.helpers.ws_utils.WsSubscriber`
per browser session per action server, so N open tabs against M servers hold
N x M connections and N x M independent rolling buffers. This module inverts
that: one :class:`WsIngest` per ``(server_key, ws_path)`` for the whole
process, writing into a shared :class:`~helao.core.servers.reflex.ringbuffer.RingBuffer`
that every browser session reads.

The second consequence matters as much as the first. Ingest runs at WebSocket
speed while rendering runs on a per-session timer, so a fast data stream no
longer drags the render loop with it -- the coupling that
``VisSubscriber.IOloop_data`` has today, where every batch schedules a document
callback.
"""

__all__ = [
    "IngestStatus",
    "WsIngest",
    "IngestRegistry",
    "normalize",
    "normalize_data_package",
    "NORMALIZERS",
    "set_registry",
    "get_registry",
]

import asyncio
import collections
import time
from dataclasses import dataclass, field
from typing import Optional

from helao.core.servers.reflex.ringbuffer import RingBuffer, RowBuffer
from helao.helpers import helao_logging as logging
from helao.helpers.ws_utils import WsSubscriber

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Config key -> WebSocket path. Mirrors the mapping the Bokeh
#: ``live_visualizer`` / ``action_visualizer`` apps use via
#: :func:`helao.core.servers.vis_subscriber.mount_visualizers`.
VIS_KEY_TO_WS_PATH = {"live_vis": "ws_live", "action_vis": "ws_data"}


def normalize(messages: list) -> tuple:
    """Turn HELAO WebSocket payloads into numeric columns and mixed rows.

    A payload is ``{datalab: (dataval, epochsec)}``. ``sim_dict`` payloads are
    flattened one level. List values extend a column; scalars append one
    element.

    Row alignment is the whole job here. Every column advances by the same
    number of rows per message -- the longest value list in that message, or
    one -- with ``nan`` filling any column that message did not carry, and
    the message's epoch repeated across all of its rows. Without that
    invariant an intermittently-published key drifts: its Nth value would
    land on the Nth message *containing* it rather than the Nth row, and the
    data silently plots against the wrong timestamps. A single tail-pad at
    the end of the batch (the earlier approach) only happens to be correct
    when a column's real values form a contiguous prefix of the batch, which
    an intermittent publisher does not guarantee.

    Values that will not coerce to ``float`` (server names, sample labels,
    status strings) are collected into per-message row dicts instead, because
    :class:`RingBuffer` is float64-only.

    Args:
        messages: Batches drained from a :class:`WsSubscriber`.

    Returns:
        ``(numeric_columns, mixed_rows)``. Every list in ``numeric_columns``
        has the same length and is positionally aligned with ``epoch``.
        ``mixed_rows`` is one dict per message that carried at least one
        non-numeric value. Malformed entries are skipped.
    """
    cols: dict = {}
    rows: list = []
    emitted = 0  # rows emitted so far, so a new column can be backfilled
    for message in messages:
        if not isinstance(message, dict):
            continue
        latest_epoch = None
        row: dict = {}
        pending: dict = {}
        for datalab, payload in message.items():
            if not isinstance(payload, (tuple, list)) or len(payload) != 2:
                continue
            dataval, epochsec = payload
            try:
                seen = float(epochsec)
                latest_epoch = seen if latest_epoch is None else max(latest_epoch, seen)
            except (TypeError, ValueError):
                pass
            if datalab == "sim_dict" and isinstance(dataval, dict):
                for k, v in dataval.items():
                    pending.setdefault(k, []).append(v)
                continue
            if isinstance(dataval, (list, tuple)):
                pending.setdefault(datalab, []).extend(dataval)
            else:
                pending.setdefault(datalab, []).append(dataval)

        numeric: dict = {}
        for name, values in pending.items():
            try:
                numeric[name] = [float(v) for v in values]
            except (TypeError, ValueError):
                row[name] = values[-1] if len(values) == 1 else values
        if row:
            rows.append(row)
        if not numeric and latest_epoch is None:
            continue

        # Every column advances by the same number of rows for this message.
        # Deferring the fill to a single tail-pad at the end of the batch
        # would silently misalign any key that publishes intermittently: its
        # Nth value would land on the Nth message *containing that key*, not
        # the Nth row.
        row_count = max((len(v) for v in numeric.values()), default=1) or 1

        for name in numeric:
            if name not in cols:
                cols[name] = [float("nan")] * emitted
        if latest_epoch is not None and "epoch" not in cols:
            cols["epoch"] = [float("nan")] * emitted

        for name, column in cols.items():
            if name == "epoch":
                # Every row from one message shares that message's
                # timestamp, so a burst of N samples repeats the epoch N
                # times rather than leaving N-1 rows with no time to plot
                # against.
                stamp = float("nan") if latest_epoch is None else latest_epoch
                column.extend([stamp] * row_count)
            else:
                values = numeric.get(name, [])
                column.extend(values)
                column.extend([float("nan")] * (row_count - len(values)))
        emitted += row_count

    return cols, rows


def normalize_data_package(messages: list) -> tuple:
    """Turn ``ws_data`` packets into numeric columns and per-message rows.

    ``/ws_data`` is served by ``data_publisher.broadcast``, and ``WsPublisher``
    defaults to an identity ``xform_func`` -- so each message is a pickled
    :class:`DataPackageModel` **object**, not a dict. Its payload lives at
    ``.datamodel.data[file_conn_key][column]`` and is reached by attribute
    access, which is why the Bokeh ``oersim_vis`` reads
    ``data_package.datamodel.status`` rather than subscripting. A dict is also
    accepted, defensively, in case a relay is configured with ``as_dict()``.

    :func:`normalize` drops these outright (they are not dicts), which left an
    action visualizer permanently empty while its status still read ``live``.

    Args:
        messages: Batches drained from a :class:`WsSubscriber` on ``ws_data``.

    Returns:
        ``(numeric_columns, rows)``. Columns are equal-length and positionally
        aligned, filled per message exactly as :func:`normalize` does. Each row
        carries the ``action_uuid`` and ``status`` of one packet, so a panel can
        reset when the streamed action changes.
    """

    def _get(obj, name):
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)

    cols: dict = {}
    rows: list = []
    emitted = 0
    for message in messages:
        datamodel = _get(message, "datamodel")
        if datamodel is None:
            continue
        data = _get(datamodel, "data")
        if not isinstance(data, dict):
            continue

        if len(data) > 1:
            # Columns from several file connections are merged by name below,
            # which silently interleaves what may be unrelated timebases. Warn
            # rather than fix: oersim publishes one connection per packet, but
            # the hte deployment is far likelier to hit this.
            LOGGER.warning(
                f"ws_data packet carries {len(data)} file connections; "
                "their columns are merged by name and may interleave"
            )
        pending: dict = {}
        for columns in data.values():
            if not isinstance(columns, dict):
                continue
            for name, values in columns.items():
                seq = values if isinstance(values, (list, tuple)) else [values]
                pending.setdefault(name, []).extend(seq)

        numeric: dict = {}
        for name, values in pending.items():
            try:
                numeric[name] = [float(v) for v in values]
            except (TypeError, ValueError):
                # e.g. composition strings alongside the numeric traces
                continue

        # Recorded before the numeric guard: a packet may carry no samples yet
        # and still mark an action boundary, and that is exactly the packet a
        # panel needs in order to reset. Dropping it would lose the transition.
        status = _get(datamodel, "status")
        rows.append(
            {
                "action_uuid": str(_get(message, "action_uuid") or ""),
                "status": str(getattr(status, "value", status) or ""),
            }
        )
        if not numeric:
            continue

        row_count = max(len(v) for v in numeric.values())
        for name in numeric:
            if name not in cols:
                cols[name] = [float("nan")] * emitted
        for name, column in cols.items():
            values = numeric.get(name, [])
            column.extend(values)
            column.extend([float("nan")] * (row_count - len(values)))
        emitted += row_count
    return cols, rows


#: Which normalizer each subscribed endpoint needs. The two carry genuinely
#: different payloads; one normalizer silently drops the other's messages.
NORMALIZERS = {"ws_live": normalize, "ws_data": normalize_data_package}


@dataclass
class IngestStatus:
    """Observable connection state for one ingest target.

    Attributes:
        state: ``"connecting"`` before the first message, ``"live"`` while
            messages arrive, ``"reconnecting"`` once the stream goes stale.
        last_epoch: Wall-clock time of the most recent message batch.
        message_count: Total messages ingested since start.
        error: Most recent error string, or ``None``.
    """

    state: str = "connecting"
    last_epoch: float = 0.0
    message_count: int = 0
    error: Optional[str] = field(default=None)


class WsIngest:
    """One process-wide subscriber feeding a ring buffer for one endpoint.

    Reconnection is not implemented here:
    :class:`~helao.helpers.ws_utils.WsSubscriber` already reconnects
    indefinitely with capped exponential backoff. This class owns the drain
    loop, normalization, and the observable :class:`IngestStatus`.

    Attributes:
        buffer: Numeric ring buffer of everything normalized from the stream.
        rows: Mixed-type rows (strings, labels) from the same stream.
        raw: Bounded deque of untransformed message batches, for panels whose
            payloads do not fit the numeric-column model.
        status: Current :class:`IngestStatus`.
    """

    def __init__(
        self,
        host: str,
        port: int,
        ws_path: str,
        *,
        capacity: int = 1_000_000,
        row_maxlen: int = 200,
        raw_maxlen: int = 50,
        drain_interval: float = 0.05,
        stale_after: float = 10.0,
    ):
        """Configure the ingest target without opening a connection.

        Args:
            host: Action server hostname.
            port: Action server port.
            ws_path: ``ws_live`` or ``ws_data``.
            capacity: Ring buffer row capacity.
            row_maxlen: Retained mixed-type rows.
            raw_maxlen: Retained raw message batches.
            drain_interval: Seconds between subscriber drains.
            stale_after: Seconds without a message before the status flips to
                ``"reconnecting"``.
        """
        self.host = host
        self.port = port
        self.ws_path = ws_path
        self.url = f"ws://{host}:{port}/{ws_path}"
        self.buffer = RingBuffer([], capacity=capacity)
        self.rows = RowBuffer(maxlen=row_maxlen)
        self.raw: collections.deque = collections.deque(maxlen=raw_maxlen)
        self.status = IngestStatus()
        self._normalize = NORMALIZERS.get(ws_path, normalize)
        self._drain_interval = drain_interval
        self._stale_after = stale_after
        self._wss: Optional[WsSubscriber] = None
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Open the subscriber and launch the drain loop. Idempotent."""
        if self._task is not None:
            return
        self._wss = WsSubscriber(self.host, self.port, self.ws_path)
        self._task = asyncio.create_task(self._drain_loop())
        LOGGER.info(f"reflex ingest subscribing to {self.url}")

    async def stop(self) -> None:
        """Cancel the drain loop and the underlying subscriber. Idempotent.

        ``gather(..., return_exceptions=True)`` returns each task's own
        ``CancelledError`` as a result instead of raising it, so the teardown
        this method exists to perform does not itself look like a failure. An
        outer cancellation -- something cancelling *this* coroutine while it is
        suspended, e.g. ``asyncio.wait_for(ingest.stop(), timeout=...)`` --
        still raises at the ``await`` and propagates, which is what the caller
        asked for. The ``finally`` clears the handles either way, so teardown
        completes on both paths.

        Inspecting ``task.cancelled()`` to tell the two cases apart does not
        work: this method always cancels the tasks itself first, so by the time
        the flag is readable it is ``True`` regardless of who cancelled the
        caller.
        """
        tasks = [
            task
            for task in (self._task, getattr(self._wss, "subscriber_task", None))
            if task is not None
        ]
        for task in tasks:
            task.cancel()
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            self._task = None
            self._wss = None

    async def _drain_loop(self) -> None:
        """Drain the subscriber, normalize, and append. Runs until cancelled."""
        assert self._wss is not None
        while True:
            try:
                messages = await self._wss.read_messages()
                if messages:
                    self.raw.append(messages)
                    cols, rows = self._normalize(messages)
                    if cols:
                        self.buffer.append(cols)
                    for row in rows:
                        self.rows.append(row)
                    self.status.state = "live"
                    self.status.last_epoch = time.time()
                    self.status.message_count += len(messages)
                    self.status.error = None
                elif (
                    self.status.state == "live"
                    and time.time() - self.status.last_epoch > self._stale_after
                ):
                    self.status.state = "reconnecting"
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # normalization/append failures
                self.status.error = f"{type(exc).__name__}: {exc}"
                LOGGER.warning(f"reflex ingest error on {self.url}: {exc}")
            await asyncio.sleep(self._drain_interval)


class IngestRegistry:
    """Process-wide map of ``(server_key, ws_path)`` to a single :class:`WsIngest`.

    Targets are discovered from the same ``live_vis`` / ``action_vis`` config
    keys the Bokeh stack uses, so a config that already declares visualizers
    needs no new keys to feed the Reflex stack.
    """

    def __init__(self, world_cfg: dict):
        """Discover targets from ``world_cfg`` without connecting.

        Args:
            world_cfg: The loaded HELAO world config.
        """
        self.world_cfg = world_cfg or {}
        self._ingests: dict = {}
        self._targets: list = []
        for server_key, server_cfg in (self.world_cfg.get("servers") or {}).items():
            if not isinstance(server_cfg, dict):
                continue
            host = server_cfg.get("host")
            port = server_cfg.get("port")
            if host is None or port is None:
                continue
            for vis_key, ws_path in VIS_KEY_TO_WS_PATH.items():
                if not server_cfg.get(vis_key):
                    continue
                target = (server_key, ws_path)
                if target not in self._targets:
                    self._targets.append(target)

    def targets(self) -> list:
        """Return the discovered ``(server_key, ws_path)`` pairs."""
        return list(self._targets)

    def start(self) -> None:
        """Create and start one :class:`WsIngest` per target. Idempotent."""
        servers = self.world_cfg.get("servers") or {}
        for server_key, ws_path in self._targets:
            if (server_key, ws_path) in self._ingests:
                continue
            cfg = servers[server_key]
            ingest = WsIngest(cfg["host"], cfg["port"], ws_path)
            ingest.start()
            self._ingests[(server_key, ws_path)] = ingest

    async def stop(self) -> None:
        """Stop every ingest and clear the map."""
        for ingest in list(self._ingests.values()):
            await ingest.stop()
        self._ingests.clear()

    def get(self, server_key: str, ws_path: str) -> Optional[WsIngest]:
        """Return the ingest for a target, or ``None`` if not started."""
        return self._ingests.get((server_key, ws_path))


_REGISTRY: Optional[IngestRegistry] = None


def set_registry(registry: IngestRegistry) -> None:
    """Install the process-wide registry. Called once from ``app.py``."""
    global _REGISTRY
    _REGISTRY = registry


def get_registry() -> Optional[IngestRegistry]:
    """Return the process-wide registry, or ``None`` before startup."""
    return _REGISTRY
