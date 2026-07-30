"""Stress test for an orchestrator's private dispatcher endpoint.

Fires ``NUM_JOBS`` concurrent ``get_status`` calls at an orchestrator on
``HOST:PORT`` using :func:`async_private_dispatcher`, logs any errors
returned by each call, and exits.

Command-line usage:
    python connection_limit.py <num_jobs> [timeout_seconds]
"""

import asyncio
import sys

from helao.helpers import helao_logging as logging
from helao.helpers.dispatcher import async_private_dispatcher

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
HOST = "127.0.0.1"
PORT = 8011
NUM_JOBS = int(sys.argv[1])
if len(sys.argv) > 2:
    TIMEOUT = int(sys.argv[2])
else:
    TIMEOUT = 30


async def main():
    """Dispatch ``NUM_JOBS`` concurrent ``get_status`` calls and exit.

    Gathers responses, logs the error component of each ``(response, error)``
    tuple, and terminates the interpreter with exit code ``0``.
    """
    server_key = "ORCH"
    private_action = "get_status"
    params_dict = {}
    json_dict = {}

    tasks = [
        async_private_dispatcher(
            server_key, HOST, PORT, private_action, params_dict, json_dict, TIMEOUT
        )
        for _ in range(NUM_JOBS)
    ]

    re_tups = await asyncio.gather(*tasks)
    LOGGER.info([err for resp, err in re_tups])
    LOGGER.info("main done")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
