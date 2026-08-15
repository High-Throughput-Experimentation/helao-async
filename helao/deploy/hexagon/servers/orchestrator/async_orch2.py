"""Hexagon orchestrator entrypoint: same module/fast name as the legacy
async_orch2 so a config flips ONLY the `deployment:` key.

**B3b: this now builds an ``OrchHost`` directly.** It used to call
``makeOrchApp``, which constructed a legacy ``OrchAPI`` and grafted the
reducer over the live ``Orch`` it created -- the graft existed only because
no native host owned the loop. One does now, so the composition is the host
itself rather than a wrap around the engine, exactly as B1's ported action
modules construct an ``ActionHost`` instead of going through
``makeActionApp``.

``makeOrchApp`` is left in place and still grafts, for any composition that
has not moved. It skips the graft when handed a native host, so the two
cannot both drive one set of queues.
"""

from helao.hexagon.app.orch_host import OrchHost

__all__ = ["makeApp"]


def makeApp(server_key) -> OrchHost:
    """Construct the native orchestrator app for ``server_key``.

    Arity matches the legacy entrypoint deliberately: the launcher calls
    ``makeApp(server_key)`` and nothing else about the launch path changes.
    """
    return OrchHost(
        server_key,
        server_key,
        "Orchestrator",
        version=3.0,
    )
