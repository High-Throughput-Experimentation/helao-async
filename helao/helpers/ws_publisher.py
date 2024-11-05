import pickle
from typing import List

import pyzstd
import websockets
from fastapi import WebSocket


class WsPublisher:
    """
    WsPublisher is a class that manages WebSocket connections and broadcasts messages from a source queue to all active connections.

    Attributes:
        active_connections (List[WebSocket]): A list of currently active WebSocket connections.
        source_queue: The queue from which messages are sourced.
        xform_func (function): A transformation function applied to each message before broadcasting.

    Methods:
        __init__(source_queue, xform_func=lambda x: x):
            Initializes the WsPublisher with a source queue and an optional transformation function.

        connect(websocket: WebSocket):
            Accepts a WebSocket connection and adds it to the list of active connections.

        disconnect(websocket: WebSocket):
            Removes a WebSocket connection from the list of active connections.

        broadcast(websocket: WebSocket):
            Subscribes to the source queue and broadcasts transformed messages to the WebSocket connection.
    """
    active_connections: List[WebSocket]

    def __init__(self, source_queue, xform_func=lambda x: x):
        """
        Initializes the WsPublisher instance.

        Args:
            source_queue (queue.Queue): The source queue from which messages will be consumed.
            xform_func (callable, optional): A transformation function to apply to each message. 
                                             Defaults to a no-op function (lambda x: x).

        Attributes:
            active_connections (list): A list to keep track of active connections.
            source_queue (queue.Queue): The source queue from which messages will be consumed.
            xform_func (callable): A transformation function to apply to each message.
        """
        self.active_connections = []
        self.source_queue = source_queue
        self.xform_func = xform_func

    async def connect(self, websocket: WebSocket):
        """
        Handles a new WebSocket connection.

        This method accepts an incoming WebSocket connection and adds it to the list of active connections.

        Args:
            websocket (WebSocket): The WebSocket connection to be accepted and added to active connections.

        Returns:
            None
        """
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """
        Disconnects a WebSocket connection.

        This method removes the given WebSocket connection from the list of active connections.

        Args:
            websocket (WebSocket): The WebSocket connection to be removed from active connections.
        """
        self.active_connections.remove(websocket)

    async def broadcast(self, websocket: WebSocket):
        """
        Broadcasts messages from the source queue to the given websocket.

        This method subscribes to the source queue and listens for messages.
        Each message is transformed using the `xform_func` and then compressed
        using `pyzstd` before being sent to the websocket.

        Args:
            websocket (WebSocket): The websocket to which messages are broadcasted.

        Raises:
            websockets.ConnectionClosedError: If the client closes the connection
                                              without sending a close frame.
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
