# -*- coding: utf-8 -*-
"""Asynchronous orchestrator example.

This server implements a general-purpose orchestrator capable of executing a mixed queue
of synchronous and asynchronous processes. It provides POST request endpoints for managing
a OrchHandler class object, the core functionality of an async orchestrator.

    Startup:
    The orchestrator server must be started AFTER all instrument and process servers
    within a configuration file. Creating server processes via the helao.py launch
    script enforces the required launch order.

    After instantiating the global OrchHandler, the object will subscribe to all process
    server status websockets using the .monitor_states() coroutine. Websocket messages
    coming from process servers will update the OrchHandler's asyncio 'data' queue, which
    in turn acts as a trigger for checks to the global blocking status while running the
    orchestrator's process dispatch loop. This design avoids continuous polling on the
    global blocking status.

    Queue:
    The orchestrator uses deque objects to maintain separate sample and process queues.
    The sample queue may be populated using POST requests to '/append_sequence' or
    '/prepend_sequence' endpoints. The process queue is determined by the 'sequence'
    method of a given sample [sequence]. Sequences are defined in an process library
    specified by the configuration. An sequence takes a sample argument and returns a
    list of processs. The process queue is repopulated once all processes on a given sample
    have finished (this prevents simultaneous execution of processes across samples).

    Dispatch:
    Sample and process queues are processed by the 'run_dispatch_loop' coroutine, which
    is created by posting a request to the '/start' server endpoint. The corresponding
    '/stop' endpoint is used to end processing but at the moment does not interrupt any
    processes in progress.

"""

__all__ = ["makeApp"]

from importlib import import_module
from fastapi import Request
from typing import Optional
import asyncio
import time


from helaocore.server import makeOrchServ, setup_process


def makeApp(confPrefix, servKey):
    config = import_module(f"helao.config.{confPrefix}").config

    app = makeOrchServ(
        config,
        servKey,
        servKey,
        "Gamry instrument/process server",
        version=2.0,
        driver_class=None
    )

    @app.post(f"/{servKey}/wait")
    async def wait(
        request: Request,
        waittime: Optional[float] = 0.0
        ):
        """Sleep process"""    
        A = await setup_process(request)
        active = await app.orch.contain_process(process = A)
        waittime = A.process_params["waittime"]
        app.orch.print_message(' ... wait process:', waittime)
        start_time = time.time()
        last_time = start_time
        while time.time()-start_time < waittime:
            await asyncio.sleep(1)
            app.orch.print_message(f" ... orch waited {(time.time()-start_time):.1f} sec / {waittime:.1f} sec")
        # await asyncio.sleep(waittime)
        app.orch.print_message(' ... wait process done')
        finished_process = await active.finish()
        return finished_process.as_dict()

    return app
