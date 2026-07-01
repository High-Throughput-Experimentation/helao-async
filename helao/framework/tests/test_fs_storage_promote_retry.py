"""fs_storage._retry_busy handles transient Windows busy-file locks.

RUNS_ACTIVE->FINISHED promotion removes a just-closed .hlo; on Windows the OS
can hold a brief lock (WinError 32 -> PermissionError). _retry_busy retries a
bounded number of times, tolerates a concurrently-removed file, and re-raises
if still locked after the last attempt.
"""
import pytest

from helao.framework.adapters import fs_storage


@pytest.mark.asyncio
async def test_retries_permissionerror_then_succeeds():
    calls = {"n": 0}

    async def thunk():
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("WinError 32: busy")
        return "done"

    result = await fs_storage._retry_busy(thunk, attempts=5, delay=0)
    assert result == "done"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_tolerates_missing_file():
    async def thunk():
        raise FileNotFoundError

    assert await fs_storage._retry_busy(thunk, attempts=3, delay=0) is None


@pytest.mark.asyncio
async def test_reraises_after_exhausting_attempts():
    calls = {"n": 0}

    async def thunk():
        calls["n"] += 1
        raise PermissionError("still locked")

    with pytest.raises(PermissionError):
        await fs_storage._retry_busy(thunk, attempts=3, delay=0)
    assert calls["n"] == 3
