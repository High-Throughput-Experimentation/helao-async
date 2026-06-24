"""SP-DEPLOY-2 follow-up: the framework orchestrator must expose a ZMQ RPC server
so async_private_dispatcher's fast-path resolves (no 3s probe-timeout per call)."""
import asyncio
import socket
import tempfile

from helao.framework.app.factory import makeApp
from helao.framework.support import config_loader as fw
from helao.helpers import config_loader as legacy
from helao.core.rpc import RPCClient, derive_rpc_port
from helao.core.rpc.zmq_rpc import RPC_PORT_OFFSET


def _free_http_port():
    """Return an http port whose derived RPC port (``+RPC_PORT_OFFSET``) is free
    and valid (<= 65535). Bind the *RPC* port (the one actually bound at startup)
    and derive the http port downward, so the derived port can't overflow."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    rpc_port = s.getsockname()[1]
    s.close()
    http_port = rpc_port - RPC_PORT_OFFSET
    assert 1024 < http_port and derive_rpc_port(http_port) <= 65535
    return http_port


def test_orch_rpc_roundtrip(tmp_path):
    port = _free_http_port()
    cfg = {
        "root": str(tmp_path / "INST"),
        "loaded_config_path": "/configs/demo.yml",
        "servers": {"ORCH": {"group": "orchestrator", "host": "127.0.0.1", "port": port}},
    }
    prev_fw, prev_legacy = fw.CONFIG, legacy.CONFIG
    fw.CONFIG = legacy.CONFIG = cfg

    async def _run():
        app = makeApp("ORCH", group="orchestrator")
        assert hasattr(app.state, "rpc_dispatcher"), "orch app has no rpc_dispatcher"
        async with app.router.lifespan_context(app):  # runs startup (binds RPC) + shutdown
            client = RPCClient(endpoint=f"tcp://127.0.0.1:{derive_rpc_port(port)}",
                               default_timeout=3.0)
            try:
                resp = await client.call("get_orch_state", timeout=3.0)
            finally:
                await client.close()
            # a successful reply with NO HTTP server running proves the RPC path served it
            assert isinstance(resp, dict) and "loop_state" in resp, resp

    try:
        asyncio.run(asyncio.wait_for(_run(), timeout=30))
    finally:
        fw.CONFIG, legacy.CONFIG = prev_fw, prev_legacy
