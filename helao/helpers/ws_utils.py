"""WebSocket pub/sub helpers.

Consolidates the former ws_publisher and ws_subscriber modules.
"""

__all__ = ["WsPublisher", "WsSubscriber", "WsSyncClient"]

import asyncio
import collections
import pickle
import time
from typing import List

import pyzstd
import websockets
from fastapi import WebSocket
from websockets.sync.client import connect


class WsPublisher:
    """
    WsPublisher manages WebSocket connections and broadcasts messages from a source queue to all active connections.

    Attributes:
        active_connections (List[WebSocket]): A list of currently active WebSocket connections.
        source_queue: The queue from which messages are sourced.
        xform_func (function): A transformation function applied to each message before broadcasting.
    """

    active_connections: List[WebSocket]

    def __init__(self, source_queue, xform_func=lambda x: x):
        self.active_connections = []
        self.source_queue = source_queue
        self.xform_func = xform_func

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, websocket: WebSocket):
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
    """A synchronous WebSocket client for reading messages from a server."""

    def __init__(self, host, port, path):
        self.data_url = f"ws://{host}:{port}/{path}"

    def read_messages(self):
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
    """Asynchronous WebSocket subscriber that buffers incoming messages."""

    def __init__(self, host, port, path, max_qlen=500):
        self.data_url = f"ws://{host}:{port}/{path}"
        self.recv_queue = collections.deque(maxlen=max_qlen)
        self.subscriber_task = asyncio.create_task(self.subscriber_loop())

    async def subscriber_loop(self):
        retry_limit = 5
        for retry_idx in range(retry_limit):
            try:
                async with websockets.connect(self.data_url) as ws:
                    while True:
                        recv_bytes = await ws.recv()
                        recv_data_dict = pickle.loads(pyzstd.decompress(recv_bytes))
                        self.recv_queue.append(recv_data_dict)
            except Exception:
                print(f"Could not connect, retrying {retry_idx+1}/{retry_limit}")
                time.sleep(2)

    async def read_messages(self):
        messages = []
        while self.recv_queue:
            messages.append(self.recv_queue.popleft())
            await asyncio.sleep(1e-4)
        return messages
