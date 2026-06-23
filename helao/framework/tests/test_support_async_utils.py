import asyncio
import pytest
from helao.framework.support.async_utils import AsyncRWLock


def test_single_reader_acquires():
    lock = AsyncRWLock()
    log = []

    async def run():
        async with lock.read_locked():
            log.append("read")

    asyncio.run(run())
    assert log == ["read"]


def test_single_writer_acquires():
    lock = AsyncRWLock()
    log = []

    async def run():
        async with lock.write_locked():
            log.append("write")

    asyncio.run(run())
    assert log == ["write"]


def test_writer_waits_for_active_reader():
    lock = AsyncRWLock()
    log = []

    async def run():
        async def reader():
            async with lock.read_locked():
                log.append("read_start")
                await asyncio.sleep(0.05)
                log.append("read_end")

        async def writer():
            await asyncio.sleep(0.01)
            async with lock.write_locked():
                log.append("write")

        await asyncio.gather(reader(), writer())

    asyncio.run(run())
    assert log.index("write") > log.index("read_end")


def test_multiple_readers_do_not_block_each_other():
    lock = AsyncRWLock()
    acquired = []

    async def run():
        async def reader(name):
            async with lock.read_locked():
                acquired.append(name)
                await asyncio.sleep(0.02)

        await asyncio.gather(reader("r1"), reader("r2"))

    asyncio.run(run())
    assert set(acquired) == {"r1", "r2"}
