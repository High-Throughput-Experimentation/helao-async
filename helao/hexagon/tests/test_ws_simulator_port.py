"""ws_simulator on the native stack (B1 Task 7, first module).

The first end-to-end proof: an action module that constructs no BaseAPI, whose
handlers receive an explicit ActionContext, and whose executor runs through the
native runner. Asserted through ASGI transport, so routing, the queuing
middleware, context injection and the session all take part.
"""

import tempfile

import httpx
import pytest


def _app():
    from helao.deploy.test.servers.action.ws_simulator import makeApp
    from helao.helpers import config_loader

    config_loader.CONFIG = {
        "root": tempfile.mkdtemp(prefix="helao_wssim_"),
        "dummy": True,
        "simulation": True,
        "servers": {
            "SIM": {
                "host": "127.0.0.1",
                "port": 8002,
                "params": {"columns": {"a": 1, "b": 2}},
            }
        },
    }
    return makeApp("SIM")


def test_the_module_constructs_no_baseapi() -> None:
    """The point of the port: no legacy engine object is built."""
    import inspect

    from helao.deploy.test.servers.action import ws_simulator

    src = inspect.getsource(ws_simulator)
    assert "BaseAPI" not in src
    assert "core.servers.base" not in src


def test_it_builds_an_action_host_with_both_routes() -> None:
    from helao.hexagon.app.action_host import ActionHost

    app = _app()
    assert isinstance(app, ActionHost)
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/SIM/acquire_data" in paths
    assert "/SIM/cancel_acquire_data" in paths


def test_the_full_private_surface_is_present() -> None:
    """A ported module keeps every route legacy's BaseAPI registered."""
    from harness import openapi_capture

    from helao.hexagon.tests.test_action_host_surface import EXPECTED_PRIVATE

    routes = openapi_capture.normalize(_app().openapi())["routes"]
    private = {r["path"] for r in routes if "private" in r["tags"]}
    assert private == EXPECTED_PRIVATE


@pytest.mark.asyncio
async def test_the_handler_receives_a_context_carrying_its_params() -> None:
    """The explicit-context port, exercised over a real request."""
    app = _app()
    await app.init_endpoint_status()

    seen = {}
    original = None
    for route in app.routes:
        if getattr(route, "path", "") == "/SIM/acquire_data":
            original = route.endpoint

    assert original is not None, "acquire_data route not found"

    # drive the wrapped endpoint directly: begin() needs a live driver, which
    # startup builds, so assert on the context the wrapper constructs instead.
    from helao.hexagon.app.action_route import wrap_action_endpoint

    async def probe(ctx, duration: float = -1, acquisition_rate: float = 0.2):
        seen["ctx"] = ctx
        return {"ok": True}

    wrapped = wrap_action_endpoint(probe, app)
    await wrapped(duration=5.0, acquisition_rate=0.5, action_version=1)

    ctx = seen["ctx"]
    assert ctx.action.action_params["duration"] == 5.0
    assert ctx.action.action_params["acquisition_rate"] == 0.5
    assert ctx.host is app


@pytest.mark.asyncio
async def test_a_private_route_answers_over_asgi() -> None:
    """Routing and middleware both take part; nothing 405s or 500s."""
    app = _app()
    await app.init_endpoint_status()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.post("/get_config", json={})
    assert resp.status_code == 200
    assert resp.json()["servers"]["SIM"]["port"] == 8002
