import asyncio
import pickle
from typing import List

import pyzstd
from fastapi import WebSocket


class WsPublisher:
    """Generic publisher class for websocket messages sent by helao servers.

    Publisher sends compressed messages and handles subscriber disconnection.
    """

    def __init__(self, source_queue, xform_func=lambda x: x):
        self.active_connections = List[WebSocket] = []
        self.source_queue = source_queue
        self.xform_func = xform_func

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self):
        async for source_msg in self.source_queue.subscribe():
            for connection in self.active_connections:
                await connection.send_bytes(
                    pyzstd.compress(pickle.dumps(self.xform_func(source_msg)))
                )
