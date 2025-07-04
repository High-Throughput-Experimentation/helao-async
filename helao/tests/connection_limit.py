import sys
import asyncio
from helao.helpers.dispatcher import async_private_dispatcher
from helao.helpers import helao_logging as logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

HOST = "127.0.0.1"
PORT = 8011
NUM_JOBS = int(sys.argv[1])
if len(sys.argv) > 2:
    TIMEOUT = int(sys.argv[2])
else:
    TIMEOUT = 30

async def main():    
    server_key = "ORCH"
    private_action = "get_status"
    params_dict = {}
    json_dict = {}

    tasks = [async_private_dispatcher(
        server_key, HOST, PORT, private_action, params_dict, json_dict, TIMEOUT
    ) for _ in range(NUM_JOBS)]

    re_tups = await asyncio.gather(*tasks)
    LOGGER.info([err for resp, err in re_tups])
    LOGGER.info('main done')
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())