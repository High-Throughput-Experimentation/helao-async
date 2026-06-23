"""Tests for the ported AsyncRWLock (SP6 W1-A)."""
import asyncio

from helao.framework.support.async_utils import AsyncRWLock


async def test_multiple_concurrent_readers():
    """Several readers can hold the lock at the same time."""
    lock = AsyncRWLock()
    inside = 0
    max_concurrent = 0
    all_in = asyncio.Event()
    release = asyncio.Event()
    n = 4

    async def reader():
        nonlocal inside, max_concurrent
        async with lock.read_locked():
            inside += 1
            max_concurrent = max(max_concurrent, inside)
            if inside == n:
                all_in.set()
            # hold until every reader is confirmed inside
            await release.wait()
            inside -= 1

    tasks = [asyncio.create_task(reader()) for _ in range(n)]
    # wait until all readers are simultaneously inside (proves concurrency)
    await asyncio.wait_for(all_in.wait(), timeout=1.0)
    assert max_concurrent == n
    assert max_concurrent > 1
    release.set()
    await asyncio.gather(*tasks)


async def test_writer_has_exclusive_access():
    """While a writer holds the lock, no reader or other writer overlaps."""
    lock = AsyncRWLock()
    active_writers = 0
    active_readers = 0
    violations = []

    async def writer():
        nonlocal active_writers, active_readers
        async with lock.write_locked():
            active_writers += 1
            if active_writers != 1 or active_readers != 0:
                violations.append(("writer", active_writers, active_readers))
            await asyncio.sleep(0.01)
            active_writers -= 1

    async def reader():
        nonlocal active_writers, active_readers
        async with lock.read_locked():
            active_readers += 1
            if active_writers != 0:
                violations.append(("reader", active_writers, active_readers))
            await asyncio.sleep(0.01)
            active_readers -= 1

    tasks = (
        [asyncio.create_task(writer()) for _ in range(3)]
        + [asyncio.create_task(reader()) for _ in range(5)]
    )
    await asyncio.gather(*tasks)
    assert violations == []


async def test_reader_preferring_writer_does_not_block_new_readers():
    """A waiting writer must not stop a fresh reader from entering."""
    lock = AsyncRWLock()
    first_reader_in = asyncio.Event()
    writer_waiting = asyncio.Event()
    second_reader_in = asyncio.Event()
    hold = asyncio.Event()

    async def first_reader():
        async with lock.read_locked():
            first_reader_in.set()
            await hold.wait()

    async def writer():
        # signal intent to acquire, then block (a reader still holds the lock)
        writer_waiting.set()
        async with lock.write_locked():
            pass

    async def second_reader():
        # this reader arrives after the writer is already waiting
        async with lock.read_locked():
            second_reader_in.set()

    r1 = asyncio.create_task(first_reader())
    await asyncio.wait_for(first_reader_in.wait(), timeout=1.0)

    w = asyncio.create_task(writer())
    await asyncio.wait_for(writer_waiting.wait(), timeout=1.0)
    # give the writer time to actually park inside write_locked() waiting
    await asyncio.sleep(0.02)

    # the new reader should still be admitted despite the waiting writer
    r2 = asyncio.create_task(second_reader())
    await asyncio.wait_for(second_reader_in.wait(), timeout=1.0)

    # writer is still parked (both readers held/hold the lock)
    assert not w.done()

    hold.set()
    await asyncio.gather(r1, r2)
    await asyncio.wait_for(w, timeout=1.0)


async def test_writer_acquires_after_readers_drain():
    """Lock is released cleanly: a writer proceeds once readers exit."""
    lock = AsyncRWLock()
    writer_done = asyncio.Event()
    readers_should_exit = asyncio.Event()
    readers_in = asyncio.Event()
    count = 0
    n = 3

    async def reader():
        nonlocal count
        async with lock.read_locked():
            count += 1
            if count == n:
                readers_in.set()
            await readers_should_exit.wait()

    async def writer():
        async with lock.write_locked():
            # must only get here after every reader has released
            assert lock._readers == 0
            writer_done.set()

    readers = [asyncio.create_task(reader()) for _ in range(n)]
    await asyncio.wait_for(readers_in.wait(), timeout=1.0)

    w = asyncio.create_task(writer())
    await asyncio.sleep(0.02)
    # writer cannot proceed while readers hold the lock
    assert not writer_done.is_set()

    readers_should_exit.set()
    await asyncio.gather(*readers)
    await asyncio.wait_for(w, timeout=1.0)
    assert writer_done.is_set()
