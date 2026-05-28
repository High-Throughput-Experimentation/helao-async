# -*- coding: utf-8 -*-
"""HTE deployment orchestrator entrypoint.

Exposes ``makeApp`` so the FastAPI launcher can instantiate the generic
:class:`helao.core.servers.orch_api.OrchAPI` for an HTE orchestration group.
The orchestrator subscribes to action servers, queues experiments and
sequences, and dispatches actions over HTTP.
"""

__all__ = ["makeApp"]

from helao.core.servers.orch_api import OrchAPI


def makeApp(server_key) -> OrchAPI:
    """Construct the FastAPI orchestrator app for ``server_key``.

    Called by ``fast_launcher.py`` after the configuration has been resolved.
    The returned :class:`OrchAPI` registers orchestrator endpoints (queue
    management, dispatch start/stop, status websockets) and is launched under
    uvicorn for the lifetime of the orchestration group.

    Args:
        server_key: Identifier of this orchestrator entry in the config
            ``servers`` block. Used as both the server key and display name.

    Returns:
        OrchAPI: Configured orchestrator application instance.
    """

    app = OrchAPI(
        server_key,
        server_key,
        "Orchestrator",
        version=3.0,
        driver_classes=None,
    )

    return app
