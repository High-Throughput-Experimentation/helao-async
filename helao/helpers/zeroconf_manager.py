"""Zeroconf service broadcast helper used by HELAO servers.

Broadcasts a service record over multicast DNS so that other HELAO components
on the network can discover this server. Service properties carry an
``instrument`` tag (the local hostname) and a ``group`` tag that designates
service resources shareable across instruments.
"""

import asyncio
import socket
from typing import List
from zeroconf import IPVersion
from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf


class ZeroconfManager:
    """Wrap :class:`zeroconf.asyncio.AsyncZeroconf` for one HELAO server.

    Holds the service info to advertise and exposes synchronous
    :meth:`enable` / :meth:`disable` helpers that drive the underlying async
    register/unregister coroutines from the cached event loop.

    Attributes:
        server_name: Logical HELAO server name.
        server_host: Hostname or address of the server.
        server_port: TCP port of the server.
        ip_version: IP version used for the advertisement (IPv4 only).
        info: The :class:`AsyncServiceInfo` record being broadcast.
        loop: Cached :mod:`asyncio` event loop used by sync helpers.
        irq: One-slot queue reserved for shutdown signaling.
    """

    def __init__(self, server_name: str, server_host: str, server_port: int):
        """Build the advertised service info for this server."""
        self.server_name = server_name
        self.server_host = server_host
        self.server_port = server_port
        self.ip_version = IPVersion.V4Only

        props = {"instrument": socket.gethostname(), "group": None}
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
        """Open the AsyncZeroconf instance and register each service info."""
        self.aiozc = AsyncZeroconf(ip_version=self.ip_version)
        tasks = [self.aiozc.async_register_service(info) for info in infos]
        background_tasks = await asyncio.gather(*tasks)
        await asyncio.gather(*background_tasks)

    async def unregister_services(self, infos: List[AsyncServiceInfo]) -> None:
        """Unregister each service info and close the AsyncZeroconf instance."""
        assert self.aiozc is not None
        tasks = [self.aiozc.async_unregister_service(info) for info in infos]
        background_tasks = await asyncio.gather(*tasks)
        await asyncio.gather(*background_tasks)
        await self.aiozc.async_close()

    def enable(self):
        """Synchronously broadcast this server's service record."""
        self.loop.run_until_complete(self.register_services([self.info]))

    def disable(self):
        """Synchronously withdraw this server's service record."""
        self.loop.run_until_complete(self.unregister_services([self.info]))
