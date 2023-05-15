import asyncio
import pickle
import collections

import pyzstd
import websockets


class WsSubscriber:
    """ Generic subscriber class for websocket messages sent by helao servers.

    Subscriber receives compressed messages from /ws_data, /ws_live, /ws_status
    endpoints, decompresses, then populates them into self.recv_queue. 
    The self.read_messages() method pops the entire queue.
    """

    def __init__(self, host, port, path, max_qlen=500):
        self.data_url = f"ws://{host}:{port}/{path}"
        self.recv_queue = collections.deque(maxlen=max_qlen)
        self.subscriber_task = asyncio.create_task(self.subscriber_loop)

    async def subscriber_loop(self):
        """Coroutine for receving broadcasted websocket messages."""
        while True:
            async with websockets.connect(self.data_url) as ws:
                recv_bytes = await ws.recv()
                recv_data_dict = pickle.loads(pyzstd.decompress(recv_bytes))
                self.recv_queue.append(recv_data_dict)

    async def read_messages(self):
        """Empties recv_queue and returns messages."""
        messages = []
        while self.recv_queue:
            messages.append(self.recv_queue.popleft())
            asyncio.sleep(1e-4)
        return messages
