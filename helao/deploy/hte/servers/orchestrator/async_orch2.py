# -*- coding: utf-8 -*-
"""HTE deployment orchestrator entrypoint.

Exposes ``makeApp`` so the FastAPI launcher can instantiate the native
:class:`helao.hexagon.app.orch_host.OrchHost` for an HTE orchestration group.
The orchestrator subscribes to action servers, queues experiments and
sequences, and dispatches actions over HTTP.

B5: this used to build a legacy ``OrchAPI``, which constructed an ``Orch`` and
let ``makeOrchApp`` graft the hexagon reducer over it. B3b gave the reducer a
native owner, so the composition is the host itself. The change is the same one
``helao/deploy/hexagon/servers/orchestrator/async_orch2.py`` already made; the
two entrypoints now differ only in which package they live in, which is what
lets B7 delete one of them.
"""

__all__ = ["makeApp"]

from helao.hexagon.app.orch_host import OrchHost


def makeApp(server_key) -> OrchHost:
    """Construct the FastAPI orchestrator app for ``server_key``.

    Called by ``fast_launcher.py`` after the configuration has been resolved.
    The returned :class:`OrchHost` registers orchestrator endpoints (queue
    management, dispatch start/stop, status websockets) and is launched under
    uvicorn for the lifetime of the orchestration group.

    Args:
        server_key: Identifier of this orchestrator entry in the config
            ``servers`` block. Used as both the server key and display name.

    Returns:
        OrchHost: Configured orchestrator application instance.
    """

    # No ``driver_classes``: OrchHost does not take it. The legacy OrchAPI did,
    # and every hte config passed None, so the argument only ever said "this
    # server has no driver" -- which the native host expresses by not having
    # the parameter.
    return OrchHost(
        server_key,
        server_key,
        "Orchestrator",
        version=3.0,
    )
