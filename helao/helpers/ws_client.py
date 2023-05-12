import asyncio
import pickle

import pyzstd
import websockets


class WsSubscriber:
    def __init__(self, host, port, path):
        self.data_url = f"ws://{host}:{port}/{path}"
        self.recv_queue = asyncio.Queue()

    async def subscriber_loop(self):
        while True:
            async with websockets.connect(self.data_url) as ws:
                recv_bytes = await ws.recv()
                recv_data_dict = pickle.loads(pyzstd.decompress(recv_bytes))
                await self.recv_queue.put(recv_data_dict)