"""Action-route wrapping: the explicit context reaches the handler (B1 Task 3b).

The two failure modes this guards are both silent. A ``ctx`` left in the exposed
signature becomes a request body field and every call fails validation; a lost
synthesized ``action`` parameter means every dispatched action arrives blank,
with the route path unchanged so no path diff notices.
"""

import inspect
import tempfile

from helao.helpers.premodels import Action
from helao.hexagon.app.action_context import ActionContext, action_version
from helao.hexagon.app.action_route import (
    build_exposed_signature,
    wrap_action_endpoint,
)


def _host():
    from helao.hexagon.app.action_host import ActionHost
    from helao.hexagon.app.wiring import PortWiring

    class _Stub:
        def meta_writer_for(self, base):
            return object()

        def __getattr__(self, name):
            raise AssertionError(f"port member {name!r} used unexpectedly")

    return ActionHost(
        server_key="SIM",
        server_title="SIM",
        description="route test",
        version=1.0,
        wiring=PortWiring(
            config=_Stub(),
            logging=_Stub(),
            clock=_Stub(),
            transport=_Stub(),
            state_persistence=_Stub(),
            status=_Stub(),
            health=_Stub(),
            artifact_store=_Stub(),
            data_sink=_Stub(),
        ),
        helao_cfg={
            "root": tempfile.mkdtemp(prefix="helao_route_test_"),
            "servers": {"SIM": {"host": "127.0.0.1", "port": 8002, "params": {}}},
        },
    )


def test_ctx_is_hidden_from_the_exposed_signature() -> None:
    """Left in, FastAPI treats it as a body field and every call 422s."""

    async def handler(ctx: ActionContext, duration: float = -1):
        return None

    exposed, _, accepted = build_exposed_signature(handler, inspect.signature(handler))
    assert "ctx" not in exposed.parameters
    assert "ctx" not in accepted
    assert "duration" in exposed.parameters


def test_action_and_version_are_synthesized_when_absent() -> None:
    """Losing the action parameter makes every dispatched action arrive blank."""

    async def handler(ctx: ActionContext, duration: float = -1):
        return None

    exposed, _, _ = build_exposed_signature(handler, inspect.signature(handler))
    assert exposed.parameters["action"].annotation is Action
    assert exposed.parameters["action_version"].default == 1


def test_the_decorator_sets_the_synthesized_version() -> None:
    @action_version(4)
    async def handler(ctx: ActionContext):
        return None

    exposed, _, _ = build_exposed_signature(handler, inspect.signature(handler))
    assert exposed.parameters["action_version"].default == 4


def test_an_inline_action_parameter_is_not_duplicated() -> None:
    async def handler(ctx: ActionContext, action: Action = None):
        return None

    exposed, _, _ = build_exposed_signature(handler, inspect.signature(handler))
    assert list(exposed.parameters).count("action") == 1


async def _call(fn, **kwargs):
    return await fn(**kwargs)


def test_the_wrapper_injects_a_context_carrying_the_request_action() -> None:
    import asyncio

    seen = {}

    async def handler(ctx: ActionContext, duration: float = -1):
        seen["ctx"] = ctx
        return "ok"

    host = _host()
    wrapped = wrap_action_endpoint(handler, host)
    result = asyncio.run(_call(wrapped, duration=7.0, action_version=1))

    assert result == "ok"
    assert isinstance(seen["ctx"], ActionContext)
    assert seen["ctx"].action.action_params["duration"] == 7.0
    assert seen["ctx"].host is host
    assert seen["ctx"].action.action_funcname == "handler"


def test_a_handler_without_ctx_still_works() -> None:
    """Not every action-tagged endpoint uses the action machinery."""
    import asyncio

    async def handler(duration: float = -1):
        return duration

    wrapped = wrap_action_endpoint(handler, _host())
    assert asyncio.run(_call(wrapped, duration=3.0, action_version=1)) == 3.0


def test_registering_an_action_route_wraps_it() -> None:
    host = _host()

    @host.action()
    async def acquire_data(ctx: ActionContext, duration: float = -1):
        return None

    paths = {r.path for r in host.routes if hasattr(r, "path")}
    assert "/SIM/acquire_data" in paths


def test_an_unbound_action_route_refuses_to_wrap() -> None:
    """A shared binding would build contexts against the wrong host."""
    from helao.hexagon.app.action_route import ActionRoute

    async def handler(ctx: ActionContext):
        return None

    try:
        ActionRoute(path="/x", endpoint=handler, tags=["action"])
    except RuntimeError as exc:
        assert "bound host" in str(exc)
    else:
        raise AssertionError("unbound ActionRoute silently wrapped the endpoint")
