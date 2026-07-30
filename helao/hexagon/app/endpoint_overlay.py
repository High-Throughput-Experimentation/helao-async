"""Endpoint override composition (spec §P4, Decision 4).

Some deployments need to replace a single endpoint inherited from a shared
``dyn_endpoints`` registrar (e.g. a driver family's standard action set)
with a versioned variant that adds extra parameters, while leaving every
other inherited endpoint untouched. The ad hoc way to do that is deployment-
side router surgery: run the base registrar, scan ``app.router.routes`` for
the target path, delete it, register the replacement, then force a schema
rebuild. That pattern works but is easy to get subtly wrong -- a typo'd
target silently leaves TWO routes registered, and the replacement's position
in the route table (which is part of the frozen ``/openapi.json`` bytes some
deployments diff against) depends on delete-then-append happening in that
exact order.

``overlay_dyn_endpoints`` makes that pattern a first-class, generic
combinator: no deployment names, no vendor specifics, only FastAPI route-
table mechanics. It composes a base ``dyn_endpoints`` registrar with a dict
of per-endpoint override registrars, keyed by the action name the override
replaces (e.g. ``{"run_CP": register_run_CP_v3}``).

Invariants enforced at call time, not just by convention:
1. The base registrar runs first, unmodified.
2. Every override target must already be a registered route -- a typo'd key
   fails loud (:class:`EndpointOverlayError`) rather than silently adding a
   second, shadowed route.
3. The target route is removed BEFORE its replacement registrar runs, and
   the replacement is asserted to land at the END of the route table -- the
   same position a manual "delete, then register anew" sequence produces.
4. ``app.openapi_schema`` is invalidated and ``app.setup()`` re-run exactly
   once, after every override has been applied -- never once per override.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Optional

from helao.core.servers.base_api import BaseAPI

DynEndpointsRegistrar = Callable[..., Optional[Awaitable[None]]]
# What `overlay_dyn_endpoints` itself returns: unlike an arbitrary caller-
# supplied registrar, the composed callable it builds is always `async def`,
# so its call site is always awaitable -- a tighter type than
# DynEndpointsRegistrar, which stays permissive for the sync-or-async inputs.
DynEndpoints = Callable[..., Awaitable[None]]

__all__ = ["EndpointOverlayError", "overlay_dyn_endpoints"]


class EndpointOverlayError(RuntimeError):
    """An override target is missing, or its replacement did not land at the
    end of the route table (the legacy delete-then-re-register position)."""


async def _run(registrar: DynEndpointsRegistrar, app: BaseAPI) -> None:
    """Invoke a ``dyn_endpoints``-shaped registrar, awaiting it if async.

    Mirrors ``helao.core.servers.base_endpoints.init_endpoint_status``'s own
    ``if callable(dyn_endpoints): await dyn_endpoints(app=...)`` -- every
    registrar in this codebase is ``async def``, but nothing here requires
    that of a caller's registrar.
    """
    result = registrar(app=app)
    if inspect.isawaitable(result):
        await result


def _target_path(app: BaseAPI, name: str) -> str:
    """The path a same-named ``@app.post(f"/{server_key}/{name}")`` route
    registers at. Every ``dyn_endpoints`` registrar in this codebase keys its
    routes off ``app.base.server.server_name``; the overlay looks the target
    up the same way so it matches whatever the base registrar just added."""
    return f"/{app.base.server.server_name}/{name}"


def _index_of(routes, path: str) -> int:
    for i, route in enumerate(routes):
        if getattr(route, "path_format", None) == path:
            return i
    return -1


def overlay_dyn_endpoints(
    base_registrar: DynEndpointsRegistrar,
    overrides: dict[str, DynEndpointsRegistrar],
) -> DynEndpoints:
    """Build a ``dyn_endpoints`` callable that layers ``overrides`` on top of
    ``base_registrar``.

    Args:
        base_registrar: The inherited registrar to run first, e.g. a shared
            driver family's standard ``dyn_endpoints`` hook.
        overrides: Maps the action name of an ALREADY-registered route (as
            added by ``base_registrar``) to a registrar that replaces it.
            Applied in dict order; each replacement is appended after the
            base set, at the position a manual delete-then-re-register
            sequence would produce.

    Returns:
        An ``async def dyn_endpoints(app)`` suitable for passing as
        ``BaseAPI(..., dyn_endpoints=...)``.

    Raises:
        EndpointOverlayError: at call time, if an override's target route
            does not exist, or its replacement did not land as a single new
            route at the end of the route table.
    """

    async def dyn_endpoints(app: BaseAPI) -> None:
        await _run(base_registrar, app)

        for name, override_registrar in overrides.items():
            routes = app.router.routes
            path = _target_path(app, name)
            target_index = _index_of(routes, path)
            if target_index == -1:
                raise EndpointOverlayError(
                    f"overlay_dyn_endpoints: no existing route at {path!r} to "
                    f"override -- the base registrar never added {name!r}, "
                    "or the override key is a typo (refusing to silently add "
                    "a second route)"
                )
            before_count = len(routes)
            del routes[target_index]
            await _run(override_registrar, app)

            added = len(routes) - (before_count - 1)
            landed_at_end = bool(routes) and (
                getattr(routes[-1], "path_format", None) == path
            )
            if added != 1 or not landed_at_end:
                last_path = getattr(routes[-1], "path_format", None) if routes else None
                raise EndpointOverlayError(
                    f"overlay_dyn_endpoints: override for {name!r} did not "
                    f"append a single replacement route at {path!r} to the "
                    "end of the route table (the position a manual delete-"
                    f"then-re-register sequence produces); added {added} "
                    f"route(s), last route is {last_path!r}"
                )

        # Rebuild exactly once, after every override -- never per-override.
        app.openapi_schema = None
        app.setup()

    return dyn_endpoints
