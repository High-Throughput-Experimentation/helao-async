import asyncio
import pickle
import collections

import pyzstd
import websockets
from websockets.sync.client import connect


class WsSyncClient:
    def __init__(self, host, port, path):
        self.data_url = f"ws://{host}:{port}/{path}"
        self.conn = connect(self.data_url)

    def read_messages(self):
        """Reads messages once."""
        recv_bytes = self.conn.recv()
        if recv_bytes:
            return pickle.loads(pyzstd.decompress(recv_bytes))
        return {}
    
    def close(self):
        self.conn.close()


class WsSubscriber:
    """Generic subscriber class for websocket messages sent by helao servers.

    Subscriber receives compressed messages from /ws_data, /ws_live, /ws_status
    endpoints, decompresses, then populates them into self.recv_queue.
    The self.read_messages() method pops the entire queue.
    """

    def __init__(self, host, port, path, max_qlen=500):
        self.data_url = f"ws://{host}:{port}/{path}"
        self.recv_queue = collections.deque(maxlen=max_qlen)
        self.subscriber_task = asyncio.create_task(self.subscriber_loop())

    async def subscriber_loop(self):
        """Coroutine for receving broadcasted websocket messages."""
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

    async def read_messages(self):
        """Empties recv_queue and returns messages."""
        messages = []
        while self.recv_queue:
            messages.append(self.recv_queue.popleft())
            await asyncio.sleep(1e-4)
        return messages
