"""Action-route wrapping: how an explicit ``ActionContext`` reaches a handler.

Legacy wraps every ``tags=["action"]`` endpoint so the invocation's ``Action``
lands in a ``ContextVar`` the handler later reads. B1 hands it over as a
parameter instead (spec D-B1.1), which means the wrapper has two jobs rather
than one:

1. **Hide ``ctx`` from FastAPI.** A ``ctx: ActionContext`` parameter left in the
   signature would be treated as a request body field, appear in the OpenAPI
   schema, and fail validation on every call. The exposed signature therefore
   drops it, and the wrapper injects the context at call time.
2. **Synthesize ``action`` and ``action_version``** when the endpoint omits
   them, exactly as legacy does. These exist so FastAPI builds the request body
   schema and so the orchestrator can introspect the endpoint --
   **losing the synthesized ``action`` parameter would mean every dispatched
   action silently arrives as a blank ``Action``**, which no route-path diff
   would notice because the path is unchanged.

The route class is bound to its host by :meth:`ActionHost.__init__` creating a
per-host subclass, rather than by a module-level global: two hosts in one process
(the concurrency tests build several) would otherwise share one binding and each
would build contexts against the wrong server.
"""

import asyncio
import functools
import inspect
from typing import Callable

from fastapi import Body
from fastapi.routing import APIRoute

from helao.helpers.premodels import Action
from helao.hexagon.app.action_context import (
    ACTION_VERSION_ATTR,
    DEFAULT_ACTION_VERSION,
    ActionContext,
    build_action,
    collect_default_params,
)

__all__ = ["ActionRoute", "bind_action_route", "wrap_action_endpoint"]

#: Name of the parameter through which a handler receives its context.
CONTEXT_PARAM = "ctx"


def _is_action_param(param: inspect.Parameter) -> bool:
    ann = param.annotation
    return isinstance(ann, type) and issubclass(ann, Action)


def _is_context_param(param: inspect.Parameter) -> bool:
    ann = param.annotation
    if isinstance(ann, type) and issubclass(ann, ActionContext):
        return True
    return param.name == CONTEXT_PARAM


def build_exposed_signature(fn: Callable, sig: inspect.Signature):
    """Return the signature FastAPI should see for *fn*.

    Drops the context parameter and synthesizes ``action``/``action_version``
    when absent, so the generated request schema matches what legacy produced
    for the same endpoint.

    Args:
        fn: The endpoint function.
        sig: Its own signature.

    Returns:
        ``(exposed_sig, accepts_var_keyword, accepted_names)`` where
        ``accepted_names`` are the parameters *fn* itself declares (excluding
        the context, which is passed separately).
    """
    params = [p for p in sig.parameters.values() if not _is_context_param(p)]
    accepts_var_keyword = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params)
    accepted_names = {
        p.name
        for p in params
        if p.kind
        not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)
    }

    injected = []
    if not any(_is_action_param(p) for p in params):
        injected.append(
            inspect.Parameter(
                "action",
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=Body({}, embed=True),
                annotation=Action,
            )
        )
    if "action_version" not in {p.name for p in params}:
        injected.append(
            inspect.Parameter(
                "action_version",
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=getattr(fn, ACTION_VERSION_ATTR, DEFAULT_ACTION_VERSION),
                annotation=int,
            )
        )

    keep = [
        p
        for p in params
        if p.kind
        not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)
    ]
    exposed = [p.replace(kind=inspect.Parameter.KEYWORD_ONLY) for p in keep] + injected
    return sig.replace(parameters=exposed), accepts_var_keyword, accepted_names


def wrap_action_endpoint(fn: Callable, host) -> Callable:
    """Wrap an action endpoint so it receives an explicit context.

    Args:
        fn: The endpoint function, declaring ``ctx`` as its context parameter.
        host: The :class:`ActionHost` serving it.

    Returns:
        A wrapper exposing the FastAPI-visible signature.
    """
    sig = inspect.signature(fn)
    exposed_sig, accepts_var_keyword, accepted_names = build_exposed_signature(fn, sig)
    default_params = collect_default_params(exposed_sig)
    wants_context = any(_is_context_param(p) for p in sig.parameters.values())

    def _forward(kwargs: dict) -> dict:
        if accepts_var_keyword:
            return dict(kwargs)
        return {k: v for k, v in kwargs.items() if k in accepted_names}

    def _context(kwargs: dict) -> ActionContext:
        action = build_action(kwargs, default_params, fn)
        return ActionContext(action=action, endpoint_func=fn, host=host)

    if asyncio.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def wrapper(**kwargs):
            forwarded = _forward(kwargs)
            if wants_context:
                forwarded[CONTEXT_PARAM] = _context(kwargs)
            return await fn(**forwarded)

    else:

        @functools.wraps(fn)
        def wrapper(**kwargs):
            forwarded = _forward(kwargs)
            if wants_context:
                forwarded[CONTEXT_PARAM] = _context(kwargs)
            return fn(**forwarded)

    wrapper.__signature__ = exposed_sig  # type: ignore[attr-defined]
    return wrapper


class ActionRoute(APIRoute):
    """``APIRoute`` that wraps ``tags=["action"]`` endpoints for context injection.

    ``host`` is set on a per-host subclass by :func:`bind_action_route`; the base
    class deliberately has none, so an unbound use fails loudly rather than
    building contexts against whichever host happened to be constructed last.
    """

    host = None

    def __init__(self, *args, **kwargs):
        tags = kwargs.get("tags") or []
        endpoint = kwargs.get("endpoint")
        if "action" in tags and endpoint is not None:
            if self.host is None:
                raise RuntimeError(
                    "ActionRoute used without a bound host; ActionHost binds a "
                    "per-host subclass via bind_action_route()."
                )
            kwargs["endpoint"] = wrap_action_endpoint(endpoint, self.host)
        super().__init__(*args, **kwargs)


def bind_action_route(host) -> type:
    """Return an :class:`ActionRoute` subclass bound to *host*.

    A per-host subclass rather than a module global: several hosts can exist in
    one process, and a shared binding would have each building contexts against
    the wrong server.
    """
    return type("BoundActionRoute", (ActionRoute,), {"host": host})
