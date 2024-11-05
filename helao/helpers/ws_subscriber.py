"""
A module for WebSocket clients, both synchronous and asynchronous, to read and process messages from a WebSocket server.
Classes:
    WsSyncClient:
        A synchronous WebSocket client for reading messages from a specified server.
            __init__(host, port, path):
    WsSubscriber:
        A class that subscribes to a WebSocket server and receives broadcasted messages asynchronously.
                Initializes the WebSocket subscriber with the given host, port, path, and optional max queue length.
"""
import asyncio
import pickle
import collections
import time

import pyzstd
import websockets
from websockets.sync.client import connect


class WsSyncClient:
    """
    A WebSocket synchronous client for reading messages from a specified server.

    Attributes:
        data_url (str): The WebSocket URL constructed from the host, port, and path.

    Methods:
        read_messages():
            Reads messages from the WebSocket server. Retries up to a specified limit
            if the connection fails. Returns the decompressed and deserialized message
            if successful, otherwise returns an empty dictionary.
    """
    def __init__(self, host, port, path):
        """
        Initializes the WebSocket subscriber with the given host, port, and path.

        Args:
            host (str): The hostname or IP address of the WebSocket server.
            port (int): The port number of the WebSocket server.
            path (str): The path to the WebSocket endpoint.

        Attributes:
            data_url (str): The constructed WebSocket URL.
        """
        self.data_url = f"ws://{host}:{port}/{path}"

    def read_messages(self):
        """
        Attempts to read and decompress messages from a WebSocket connection.

        This method tries to establish a connection to the WebSocket server
        specified by `self.data_url` and read messages from it. The messages
        are expected to be compressed using `pyzstd` and serialized using
        `pickle`. If the connection or reading fails, it will retry up to
        `retry_limit` times with a delay between retries.

        Returns:
            dict: The decompressed and deserialized message if successful,
              otherwise an empty dictionary.

        Raises:
            Exception: If an error occurs during connection or message reading.
        """
        retry_limit = 5
        for retry_idx in range(retry_limit):
            try:
                with connect(self.data_url) as conn:
                    recv_bytes = conn.recv()
                if recv_bytes:
                    return pickle.loads(pyzstd.decompress(recv_bytes))
            except Exception:
                print(
                    f"Could not connect, retrying {retry_idx+1}/{retry_limit}"
                )
                time.sleep(2)
        return {}

class WsSubscriber:
    """
    WsSubscriber is a class that subscribes to a WebSocket server and receives broadcasted messages.

    Attributes:
        data_url (str): The WebSocket URL constructed from the host, port, and path.
        recv_queue (collections.deque): A deque to store received messages with a maximum length.
        subscriber_task (asyncio.Task): An asyncio task that runs the subscriber loop.

    Methods:
        __init__(host, port, path, max_qlen=500):
            Initializes the WsSubscriber with the given host, port, path, and optional max queue length.
        
        subscriber_loop():
            Coroutine that connects to the WebSocket server and receives messages, retrying on failure.
        
        read_messages():
            Asynchronously empties the recv_queue and returns the messages.
    """

    def __init__(self, host, port, path, max_qlen=500):
        """
        Initializes the WebSocket subscriber.

        Args:
            host (str): The hostname or IP address of the WebSocket server.
            port (int): The port number of the WebSocket server.
            path (str): The path to the WebSocket endpoint.
            max_qlen (int, optional): The maximum length of the receive queue. Defaults to 500.
        """
        self.data_url = f"ws://{host}:{port}/{path}"
        self.recv_queue = collections.deque(maxlen=max_qlen)
        self.subscriber_task = asyncio.create_task(self.subscriber_loop())

    async def subscriber_loop(self):
        """
        Asynchronous method to handle the subscription loop for receiving data.

        This method attempts to connect to a WebSocket server at `self.data_url` and 
        receive data in a loop. The received data is expected to be compressed with 
        `pyzstd` and serialized with `pickle`. The decompressed and deserialized data 
        is appended to `self.recv_queue`.

        If the connection fails, it will retry up to `retry_limit` times with a delay 
        of 2 seconds between each retry.

        Attributes:
            retry_limit (int): The number of times to retry the connection before giving up.
            retry_idx (int): The current retry attempt index.
            recv_bytes (bytes): The raw bytes received from the WebSocket.
            recv_data_dict (dict): The decompressed and deserialized data received from the WebSocket.

        Raises:
            Exception: If an error occurs during the connection or data reception process.
        """
        retry_limit = 5
        for retry_idx in range(retry_limit):
            try:
                async with websockets.connect(self.data_url) as ws:
                    while True:
                        recv_bytes = await ws.recv()
                        recv_data_dict = pickle.loads(pyzstd.decompress(recv_bytes))
                        self.recv_queue.append(recv_data_dict)
            except Exception:
                print(
                    f"Could not connect, retrying {retry_idx+1}/{retry_limit}"
                )
                time.sleep(2)

    async def read_messages(self):
        """
        Asynchronously reads messages from the receive queue.

        This method continuously reads messages from the `recv_queue` until it is empty.
        Each message is appended to a list which is returned at the end.

        Returns:
            list: A list of messages read from the `recv_queue`.
        """
        messages = []
        while self.recv_queue:
            messages.append(self.recv_queue.popleft())
            await asyncio.sleep(1e-4)
        return messages
