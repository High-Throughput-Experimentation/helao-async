# -*- coding: utf-8 -*-
"""Asynchronous orchestrator example.

This server implements a general-purpose orchestrator capable of executing a mixed queue
of synchronous and asynchronous actions. It provides POST request endpoints for managing
a OrchHandler class object, the core functionality of an async orchestrator.

    Startup:
    The orchestrator server must be started AFTER all instrument and action servers
    within a configuration file. Creating server actions via the launch.py launch
    script enforces the required launch order.

    After instantiating the global OrchHandler, the object will subscribe to all action
    server status websockets using the .monitor_states() coroutine. Websocket messages
    coming from action servers will update the OrchHandler's asyncio 'data' queue, which
    in turn acts as a trigger for checks to the global blocking status while running the
    orchestrator's action dispatch loop. This design avoids continuous polling on the
    global blocking status.

    Queue:
    The orchestrator uses deque objects to maintain separate sample and action queues.
    The sample queue may be populated using POST requests to '/append_experiment' or
    '/prepend_experiment' endpoints. The action queue is determined by the 'experiment'
    method of a given sample [experiment]. Experiments are defined in an action library
    specified by the configuration. An experiment takes a sample argument and returns a
    list of actions. The action queue is repopulated once all actions on a given sample
    have finished (this prevents simultaneous execution of actions across samples).

    Dispatch:
    Sample and action queues are actioned by the 'run_dispatch_loop' coroutine, which
    is created by posting a request to the '/start' server endpoint. The corresponding
    '/stop' endpoint is used to end experimenting but at the moment does not interrupt any
    actions in progress.

"""

__all__ = ["makeApp"]

from helao.servers.orch_api import OrchAPI


def makeApp(server_key):

    app = OrchAPI(
        server_key,
        server_key,
        "Orchestrator",
        version=3.0,
        driver_classes=None,
    )

    return app
