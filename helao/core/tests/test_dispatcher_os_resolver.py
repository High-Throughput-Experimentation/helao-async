"""helao's aiohttp clients resolve names the way the OS does, even with aiodns.

aiohttp makes its c-ares ``AsyncResolver`` the default whenever ``aiodns`` is
importable. c-ares skips the OS resolver, so a station whose own name is not in
DNS could not reach its own servers (anec-03, 2026-11-11: every pre-dispatch
HEAD probe failed with ``ClientConnectorDNSError``).
"""

import asyncio

import aiohttp
import aiohttp.abc
import aiohttp.connector

from helao.helpers import dispatcher


class _FakeAiodnsResolver(aiohttp.abc.AbstractResolver):
    """Stands in for the AsyncResolver aiohttp picks when aiodns is installed."""

    def __init__(self, *args, **kwargs):
        pass

    async def resolve(self, host, port=0, family=0):  # pragma: no cover
        raise OSError("DNS server returned answer with no data")

    async def close(self):
        pass


def _resolver_type(make_connector):
    async def main():
        conn = make_connector()
        try:
            return type(conn._resolver)
        finally:
            await conn.close()

    return asyncio.run(main())


def test_os_resolver_connector_ignores_an_aiodns_default(monkeypatch):
    monkeypatch.setattr(aiohttp.connector, "DefaultResolver", _FakeAiodnsResolver)
    # The patch is effective: a bare connector now gets the aiodns-style resolver.
    assert _resolver_type(aiohttp.TCPConnector) is _FakeAiodnsResolver
    # helao's connector does not.
    assert _resolver_type(dispatcher.os_resolver_connector) is aiohttp.ThreadedResolver


def test_os_resolver_connector_passes_connector_options_through():
    async def main():
        conn = dispatcher.os_resolver_connector(force_close=True, limit=7)
        try:
            return conn.force_close, conn.limit
        finally:
            await conn.close()

    assert asyncio.run(main()) == (True, 7)
