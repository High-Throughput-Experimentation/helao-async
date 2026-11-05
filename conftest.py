"""Root pytest fixtures.

run_tests.py runs one pytest process per file, which hid process-global leaks;
pytest-xdist workers run many files in one process. Restore the two singletons
tests are known to replace, plus the process server key, so one file cannot
poison the next.
"""

import logging

import pytest


@pytest.fixture(autouse=True)
def _restore_helao_singletons():
    from helao.helpers import artifact_hash, config_loader, helao_logging

    logger, config = helao_logging.LOGGER, config_loader.CONFIG
    server_key = helao_logging.SERVER_KEY
    tool_root, fallback = artifact_hash._TOOL_ROOT, artifact_hash._FALLBACK
    yield
    artifact_hash._TOOL_ROOT, artifact_hash._FALLBACK = tool_root, fallback
    helao_logging.SERVER_KEY = server_key
    cur = helao_logging.LOGGER
    if cur is not logger and isinstance(cur, logging.Logger):
        for h in list(cur.handlers):
            cur.removeHandler(h)
            h.close()
    helao_logging.LOGGER = logger
    config_loader.CONFIG = config
