"""An action on a native host must leave artifacts on disk (B1 / D1+D2).

Every golden-master gap left after the status spine landed has the same
shape: the SIM actions run, return 200, and produce **nothing** -- no
``-act.yml``, no ``.hlo``, no ``.prg``, no S3 record -- while the ORCH
``wait`` actions beside them produce all four. Read from the capture tree
that looks like a syncer problem; it is not. The syncer can only ship what
the write path wrote.

Diagnosing it through the capture rig costs a launch, a scenario, a quiesce
and a snapshot per attempt, and yields a *tree* rather than a traceback --
which is how the same defect got labelled "manual actions write nothing"
(D1) and "the sync leg is incomplete" (D2) on two separate occasions.

This module reproduces it over ASGI in about a second, with the exception
intact. It is deliberately an *outcome* test: it asserts files exist on
disk, not that some collaborator was called, because every previous fix
along this path (init_act, file_conn_keys, write_act) satisfied a
call-level expectation and still wrote nothing.
"""

import asyncio
import tempfile
from pathlib import Path

import httpx
import pytest


def _app(root: str):
    from helao.deploy.test.servers.action.ws_simulator import makeApp
    from helao.helpers import config_loader

    config_loader.CONFIG = {
        "root": root,
        "dummy": True,
        "simulation": True,
        "run_type": "simulation",
        "servers": {
            "SIM": {
                "host": "127.0.0.1",
                "port": 8002,
                "group": "action",
                "params": {"columns": {"a": 1, "b": 2}},
            }
        },
    }
    return makeApp("SIM")


async def _started_app(root: str):
    """Build the host and run its startup handlers.

    ``httpx.ASGITransport`` does not run lifespan events, and the startup
    handler is what builds the driver and starts the status spine -- without
    it the action has nothing to acquire from.
    """
    app = _app(root)
    for handler in app.router.on_startup:
        # _rpc_startup binds the co-located ZMQ ROUTER on port+10000, which
        # collides with anything already serving that port (a running rig, a
        # sibling test). The RPC mirror plays no part in an HTTP action.
        if handler.__name__ == "_rpc_startup":
            continue
        result = handler()
        if hasattr(result, "__await__"):
            await result
    await app.init_endpoint_status()
    return app


def _run_files(root: str) -> list[Path]:
    """Every file under the run trees, whatever stage they reached."""
    found: list[Path] = []
    for top in ("RUNS_ACTIVE", "RUNS_FINISHED", "RUNS_SYNCED", "RUNS_DIAG"):
        base = Path(root) / top
        if base.exists():
            found.extend(p for p in base.rglob("*") if p.is_file())
    return found


@pytest.mark.asyncio
async def test_an_action_writes_its_meta_and_data_files() -> None:
    root = tempfile.mkdtemp(prefix="helao_artifacts_")
    app = await _started_app(root)

    # The executor reads the live buffer on its first poll, and the buffer is
    # filled by live_buffer_task folding what the driver's 10 Hz loop
    # publishes. On a real rig an action always arrives long after the first
    # fold; here they start together, so wait for it rather than racing it.
    for _ in range(200):
        if "sim_dict" in app.live_buffer:
            break
        await asyncio.sleep(0.01)
    assert "sim_dict" in app.live_buffer, (
        "live_buffer never filled -- live_buffer_task is not folding live_q, "
        "so every executor poll would KeyError and the action write nothing"
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.post(
            "/SIM/acquire_data",
            params={"duration": 2.0, "acquisition_rate": 0.2},
            json={},
        )
    assert resp.status_code == 200, resp.text

    # The POST returns when the action is accepted; the executor finishes and
    # the finalizer writes afterwards. Poll for the session to close rather
    # than sleeping a fixed interval.
    for _ in range(600):
        if not app.actives:
            break
        await asyncio.sleep(0.05)
    assert not app.actives, f"action never finished: {list(app.actives)}"
    await asyncio.sleep(0.2)  # let the finalizer's writes land

    files = _run_files(root)
    names = sorted(p.name for p in files)
    assert files, (
        "the action returned 200 and wrote nothing under any RUNS_* tree; "
        f"root contents: {sorted(p.name for p in Path(root).iterdir())}"
    )
    assert any(n.endswith("-act.yml") for n in names), f"no act meta file: {names}"
    assert any(n.endswith(".hlo") for n in names), f"no hlo data file: {names}"
