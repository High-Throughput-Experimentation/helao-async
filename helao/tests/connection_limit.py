import sys
import asyncio
from helao.helpers.dispatcher import async_private_dispatcher

HOST = "127.0.0.1"
PORT = 8011
NUM_JOBS = int(sys.argv[1])

async def main():    
    server_key = "ORCH"
    private_action = "get_status"
    params_dict = {}
    json_dict = {}

    tasks = [async_private_dispatcher(
        server_key, HOST, PORT, private_action, params_dict, json_dict
    ) for _ in range(NUM_JOBS)]

    re_tups = await asyncio.gather(*tasks)
    print(re_tups)
    print('main done')
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())