"""Cross-cutting helper utilities for HELAO servers.

Exposes :data:`async_copy`, an awaitable wrapper around :func:`shutil.copy`
produced via :func:`aiofiles.os.wrap`.
"""
import shutil
from aiofiles.os import wrap

async_copy = wrap(shutil.copy)
