"""Hexagon orchestrator entrypoint: same module/fast name as the legacy
async_orch2 so a config flips ONLY the `deployment:` key."""

from helao.hexagon.app.factory import makeOrchApp

__all__ = ["makeApp"]

FACTORY = makeOrchApp


def makeApp(server_key):
    return FACTORY(server_key)
