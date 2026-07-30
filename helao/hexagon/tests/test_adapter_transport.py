"""Transport adapter: ZMQ-first + HTTP-fallback wrap, and the MANDATORY
co-located RPC mirror (spec §7.1) verified against a REAL HelaoFastAPI —
fixture-fidelity rule §10.1: routes registered through the real registration
code, never hand-rolled fakes."""

import asyncio
import time

import pytest

from helao.core.error import ErrorCodes
from helao.hexagon.adapters.legacy.config import LegacyConfigAdapter
from helao.hexagon.adapters.legacy.transport import LegacyTransportAdapter
from helao.hexagon.ports.transport import TransportPort

HOST, PORT = "127.0.0.1", 8123  # RPC mirror -> 18123


def _world():
    return {
        "root": "/tmp/hex_t5",
        "dummy": True,
        "simulation": True,
        "servers": {
            "T5SRV": {"host": HOST, "port": PORT, "group": "action", "fast": "x"}
        },
    }


def test_transport_conformance():
    a = LegacyTransportAdapter(LegacyConfigAdapter(_world()))
    assert isinstance(a, TransportPort)


@pytest.mark.asyncio
async def test_check_endpoint_false_on_dead_peer():
    a = LegacyTransportAdapter(LegacyConfigAdapter(_world()))
    assert await a.check_endpoint(f"http://{HOST}:59998/nothing", timeout=1.0) is False


@pytest.mark.asyncio
async def test_private_dispatch_roundtrip_via_colocated_rpc():
    """Spin a REAL HelaoFastAPI (which auto-mirrors POST routes onto the
    ROUTER at http_port+10000), dispatch to it, and assert the fast path:
    a correct reply well under the 3 s probe timeout (the plain-FastAPI
    failure mode this contract exists to prevent — the operator
    blank-render incident, spec §7.1)."""
    import uvicorn

    from helao.helpers import config_loader

    world = _world()
    if config_loader.CONFIG is None:
        config_loader.install_global_config(world)

    from helao.helpers.server_api import HelaoFastAPI

    app = HelaoFastAPI(helao_srv="T5SRV", title="t5", description="", version="1")

    @app.post("/echo_probe")
    def echo_probe(value: int):
        return {"value": value, "server": "T5SRV"}

    cfg = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(cfg)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.1)
        assert server.started

        a = LegacyTransportAdapter(LegacyConfigAdapter(world))
        t0 = time.monotonic()
        resp, err = await a.dispatch_private(
            "T5SRV", HOST, PORT, "echo_probe", params_dict={"value": 7}
        )
        elapsed = time.monotonic() - t0
        assert err is ErrorCodes.none
        assert resp == {"value": 7, "server": "T5SRV"}
        assert elapsed < 2.5, (
            f"private dispatch took {elapsed:.2f}s — RPC mirror missing? "
            "(3 s probe timeout burned before HTTP fallback)"
        )
        # HEAD-probe a GET-capable route (FastAPI's auto-generated
        # /openapi.json): /echo_probe itself is POST-only, and Starlette
        # only auto-supports HEAD on routes that also accept GET, so a
        # HEAD to /echo_probe would 405 regardless of server health.
        assert await a.check_endpoint(f"http://{HOST}:{PORT}/openapi.json") is True
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)
        from helao.helpers.dispatcher import aclose_all_rpc_clients

        await aclose_all_rpc_clients()
