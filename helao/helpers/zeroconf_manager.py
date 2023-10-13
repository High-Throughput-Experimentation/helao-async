"""Zeroconf service broadcast class used by HELAO servers

Service properties will include instrument tag and a broader group tag. The group tag
will designate service resources that may be shared across instruments.

"""

import asyncio
import socket
from typing import List
from zeroconf import IPVersion
from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf


class ZeroconfManager:
    def __init__(self, server_name: str, server_host: str, server_port: int):
        self.server_name = server_name
        self.server_host = server_host
        self.server_port = server_port
        self.ip_version = IPVersion.V4Only
        
        props = {'instrument': socket.gethostname(), 'group': None}
        self.info = AsyncServiceInfo(
            "_http._tcp.local.",
            "Paul's Test Web Site._http._tcp.local.",
            addresses=[socket.inet_aton("127.0.0.1")],
            port=80,
            properties=props,
            server="ash-2.local.",
        )
        self.loop = asyncio.get_event_loop()
        self.irq = asyncio.Queue(1)


    async def register_services(self, infos: List[AsyncServiceInfo]) -> None:
        self.aiozc = AsyncZeroconf(ip_version=self.ip_version)
        tasks = [self.aiozc.async_register_service(info) for info in infos]
        background_tasks = await asyncio.gather(*tasks)
        await asyncio.gather(*background_tasks)

    async def unregister_services(self, infos: List[AsyncServiceInfo]) -> None:
        assert self.aiozc is not None
        tasks = [self.aiozc.async_unregister_service(info) for info in infos]
        background_tasks = await asyncio.gather(*tasks)
        await asyncio.gather(*background_tasks)
        await self.aiozc.async_close()

    def enable(self):
        self.loop.run_until_complete(self.register_services([self.info]))

    def disable(self):
        self.loop.run_until_complete(self.unregister_services([self.info]))