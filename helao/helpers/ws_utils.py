"""WebSocket publisher/subscriber helpers used by HELAO server fan-out.

Messages are pickled and zstd-compressed on the wire. :class:`WsPublisher`
fans an in-process queue out to many WebSocket clients, :class:`WsSubscriber`
asynchronously buffers received messages, and :class:`WsSyncClient` is a
blocking one-shot reader.
"""

__all__ = ["WsPublisher", "WsSubscriber", "WsSyncClient"]

import asyncio
import collections
import pickle
import time

import pyzstd
import websockets
from fastapi import WebSocket
from websockets.sync.client import connect

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class WsPublisher:
    """Broadcast messages from a multi-subscriber queue to WebSocket clients.

    Each message is run through ``xform_func``, pickled, and zstd-compressed
    before being written to a connected WebSocket.

    Attributes:
        active_connections: WebSocket connections that have completed handshake.
        source_queue: Multi-subscriber queue producing source messages.
        xform_func: Callable applied to each message before serialization.
    """

    active_connections: list[WebSocket]

    def __init__(self, source_queue, xform_func=lambda x: x):
        """Capture the source queue and optional message transform."""
        self.active_connections = []
        self.source_queue = source_queue
        self.xform_func = xform_func

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket handshake and track the connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """Remove ``websocket`` from the active set."""
        self.active_connections.remove(websocket)

    async def broadcast(self, websocket: WebSocket):
        """Subscribe to the source queue and forward messages to ``websocket``.

        Runs until the client closes the connection; on close the subscriber
        is removed from the source queue.
        """
        src_sub = self.source_queue.subscribe()
        try:
            async for source_msg in self.source_queue.subscribe():
                await websocket.send_bytes(
                    pyzstd.compress(pickle.dumps(self.xform_func(source_msg)))
                )
        except websockets.ConnectionClosedError:
            print("Client closed connection, but no close frame received or sent.")
            if src_sub in self.source_queue.subscribers:
                self.source_queue.remove(src_sub)


class WsSyncClient:
    """Blocking single-shot WebSocket reader for HELAO publisher streams."""

    def __init__(self, host, port, path):
        """Build the ``ws://`` URL for the target endpoint."""
        self.data_url = f"ws://{host}:{port}/{path}"

    def read_messages(self) -> dict:
        """Connect, receive one message, and return the decoded payload.

        Retries up to five times on connection failure, sleeping two seconds
        between attempts.

        Returns:
            Decoded message dict, or ``{}`` if all retries fail.
        """
        retry_limit = 5
        for retry_idx in range(retry_limit):
            try:
                with connect(self.data_url) as conn:
                    recv_bytes = conn.recv()
                if recv_bytes:
                    return pickle.loads(pyzstd.decompress(recv_bytes))
            except Exception:
                print(f"Could not connect, retrying {retry_idx+1}/{retry_limit}")
                time.sleep(2)
        return {}


class WsSubscriber:
    """Async WebSocket subscriber that buffers decoded messages in a deque.

    A background task connects to the target URL and pushes every decoded
    message into ``recv_queue`` (bounded by ``max_qlen``).
    """

    def __init__(self, host, port, path, max_qlen=500):
        """Start the background subscriber task targeting ``ws://host:port/path``."""
        self.data_url = f"ws://{host}:{port}/{path}"
        self.recv_queue = collections.deque(maxlen=max_qlen)
        self.subscriber_task = asyncio.create_task(self.subscriber_loop())

    async def subscriber_loop(self):
        """Connect to the publisher and feed decoded messages into ``recv_queue``.

        Reconnects indefinitely so the subscriber survives a restart of the
        target server (hot-reload, CTRL-r, crash, transient network drop). Uses
        a capped exponential backoff, reset after each successful connect, and a
        non-blocking ``await asyncio.sleep`` so it never stalls the event loop.
        The task ends only when cancelled (``CancelledError`` derives from
        ``BaseException`` and is intentionally not caught here).
        """
        backoff = 1.0
        max_backoff = 30.0
        while True:
            try:
                async with websockets.connect(self.data_url) as ws:
                    if backoff != 1.0:
                        LOGGER.info(f"WsSubscriber (re)connected to {self.data_url}")
                    backoff = 1.0  # reset after a successful connect
                    while True:
                        recv_bytes = await ws.recv()
                        recv_data_dict = pickle.loads(pyzstd.decompress(recv_bytes))
                        self.recv_queue.append(recv_data_dict)
            except Exception:
                LOGGER.warning(
                    f"WsSubscriber lost/failed connection to {self.data_url}; "
                    f"reconnecting in {backoff:.0f}s."
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def read_messages(self) -> list:
        """Drain and return every buffered message in FIFO order."""
        messages = []
        while self.recv_queue:
            messages.append(self.recv_queue.popleft())
            await asyncio.sleep(1e-4)
        return messages
