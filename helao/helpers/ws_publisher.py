import pickle
from typing import List

import pyzstd
import websockets
from fastapi import WebSocket


class WsPublisher:
    """Generic publisher class for websocket messages sent by helao servers.

    Publisher sends compressed messages and handles subscriber disconnection.
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
            self.source_queue.remove(src_sub)
