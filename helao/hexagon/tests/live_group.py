"""In-process REAL-transport hexagon group for §10.3 precise-interleaving
items (P1b2b: items 1, 3, 5).

Boots the REAL makeOrchApp/makeActionApp compositions under uvicorn inside
the test's event loop — real HTTP routes registered through the real
registration code, and the co-located ZMQ RPC mirrors HelaoFastAPI
auto-registers on http_port+10000 (§10.1 fixture-fidelity; boot pattern
proven by test_adapter_transport.py). Race injection happens via
app.hexagon_graft.runtime.handle(event) from a concurrent task (DD-3).

NOT a stub orch: the orchestrator is the real legacy Orch wrapped by the
P1b1 graft; the SIM is the real ws_simulator makeApp, and DB is the real
legacy sim_db_server (its syncer is on the ORCH finish path). Single
process == shared CONFIG dict + logging singleton (a documented deviation
from launched groups; items 2/4/6/7 run against a real launched group
instead).

Ports 8101/8102/8110 (RPC mirrors 18101/18102/18110) so a live goldenhex
launch on 8001/8002/8010 never collides with pytest."""

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn

from helao.core.error import ErrorCodes
from helao.helpers import config_loader
from helao.helpers import helao_logging
from helao.helpers.dispatcher import aclose_all_rpc_clients, async_private_dispatcher
from helao.helpers.helao_logging import make_logger
from helao.helpers.premodels import ExperimentPlanMaker, Sequence
from helao.helpers.time_utils import gen_uuid
from helao.hexagon.domain.models import LoopStatus

ORCH_HOST, ORCH_PORT = "127.0.0.1", 8101  # RPC mirror -> 18101
SIM_HOST, SIM_PORT = "127.0.0.1", 8102  # RPC mirror -> 18102
DB_HOST, DB_PORT = "127.0.0.1", 8110  # RPC mirror -> 18110

_REPO_ROOT = str(Path(__file__).resolve().parents[3])

__all__ = [
    "LiveGroup",
    "ORCH_HOST",
    "ORCH_PORT",
    "SIM_HOST",
    "SIM_PORT",
    "DB_HOST",
    "DB_PORT",
    "build_ws_sequence",
    "live_group",
    "orch_call",
    "wait_for_glob",
    "wait_parked",
]


@dataclass
class LiveGroup:
    orch: Any  # legacy Orch — untyped (Any) to avoid import cycles in tests
    runtime: Any  # HexRuntime — untyped to avoid import cycles in tests
    orch_app: Any
    sim_app: Any
    db_app: Any
    world: dict
    root: str


def make_world(root: str) -> dict:
    """goldenhex.yml-shaped world dict on the test-local ports, plus the
    launcher-augmented keys (loaded_config_path/helao_repo_root/
    helao_credentials_path/alert_config_path) that read_config() normally
    injects and that legacy Orch/Base startup requires (spike findings #1)."""
    return {
        "dummy": True,
        "simulation": True,
        "run_type": "simulation",
        "root": root,
        "loaded_config_path": os.path.join(
            _REPO_ROOT, "helao", "deploy", "test", "configs", "goldenhex.yml"
        ),
        "helao_repo_root": _REPO_ROOT,
        "helao_credentials_path": "",
        "alert_config_path": "",
        "experiment_libraries": [
            "simulatews_exp",
            "helao/deploy/test/experiments/TEST_exp.py",
        ],
        "sequence_libraries": ["helao/deploy/test/sequences/TEST_seq.py"],
        "servers": {
            "ORCH": {
                "host": ORCH_HOST,
                "port": ORCH_PORT,
                "group": "orchestrator",
                "fast": "async_orch2",
                "deployment": "hexagon",
                "params": {},
            },
            "SIM": {
                "host": SIM_HOST,
                "port": SIM_PORT,
                "group": "action",
                "fast": "ws_simulator",
                "deployment": "hexagon",
                "params": {},
            },
            "DB": {
                "host": DB_HOST,
                "port": DB_PORT,
                "group": "action",
                "fast": "sim_db_server",
                "params": {"aws_bucket": "helao-sim", "s3_record": True},
            },
        },
    }


async def _serve(app, host: str, port: int):
    cfg = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(cfg)
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            return server, task
        await asyncio.sleep(0.1)
    raise RuntimeError(f"uvicorn on {host}:{port} never started")


@asynccontextmanager
async def live_group(tmp_root: str, ntp_offset_s: float = 0.0):
    """Boot SIM+DB, wait until up, THEN ORCH (spike finding #3 ordering: its
    startup graft + peer probes must see live action/DB servers), reproducing
    the §9.1 ordering: root/LOGS + ntpLastSync.txt + singleton logger exist
    BEFORE any composition import runs. The offset file also keeps Base
    from hitting live NTP in-process (spike finding #4)."""
    log_dir = os.path.join(tmp_root, "LOGS")
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "ntpLastSync.txt"), "w") as f:
        f.write(f"1752600000.0,{ntp_offset_s}")
    world = make_world(tmp_root)
    prev_cfg = config_loader.CONFIG
    prev_logger = helao_logging.LOGGER
    config_loader.CONFIG = world  # test-scoped install; restored on exit
    if helao_logging.LOGGER is None:
        helao_logging.LOGGER = make_logger("hexlive", log_dir=log_dir)

    from helao.hexagon.app.factory import makeActionApp, makeOrchApp
    from helao.deploy.test.servers.action.sim_db_server import makeApp as db_makeApp

    sim_app = makeActionApp("SIM", "helao.deploy.test.servers.action.ws_simulator")
    db_app = db_makeApp("DB")
    sim_server, sim_task = await _serve(sim_app, SIM_HOST, SIM_PORT)
    db_server, db_task = await _serve(db_app, DB_HOST, DB_PORT)
    orch_app = makeOrchApp("ORCH")
    orch_server, orch_task = await _serve(orch_app, ORCH_HOST, ORCH_PORT)
    try:
        graft = None
        for _ in range(200):  # graft lands on the startup event, after app.orch
            graft = getattr(orch_app, "hexagon_graft", None)
            if graft is not None:
                break
            await asyncio.sleep(0.05)
        assert graft is not None, "hexagon graft never installed at startup"
        yield LiveGroup(
            orch=orch_app.orch,
            runtime=graft.runtime,
            orch_app=orch_app,
            sim_app=sim_app,
            db_app=db_app,
            world=world,
            root=tmp_root,
        )
    finally:
        orch_server.should_exit = True
        sim_server.should_exit = True
        db_server.should_exit = True
        await asyncio.wait_for(
            asyncio.gather(orch_task, sim_task, db_task, return_exceptions=True),
            timeout=20,
        )
        await aclose_all_rpc_clients()
        config_loader.CONFIG = prev_cfg
        helao_logging.LOGGER = prev_logger


async def orch_call(endpoint: str, params=None, body=None) -> dict:
    """Real-transport call into the live ORCH (ZMQ RPC first, HTTP fallback)."""
    resp, err = await async_private_dispatcher(
        "ORCH", ORCH_HOST, ORCH_PORT, endpoint, params or {}, body or {}
    )
    assert err is ErrorCodes.none, f"/{endpoint} -> {err}"
    return resp


def build_ws_sequence(
    n_exps: int, wait_time: float = 1.0, data_duration: float = 2.0
) -> Sequence:
    """SIM_websocket_data experiments: 4 actions each (wait, acquire, x2)."""
    epm = ExperimentPlanMaker()
    for _ in range(n_exps):
        epm.add(
            "SIM_websocket_data",
            {"wait_time": wait_time, "data_duration": data_duration},
        )
    return Sequence(
        sequence_name="SIM_websocket_data_seq",
        sequence_label="p1b2b",
        sequence_params={"wait_time": wait_time, "data_duration": data_duration},
        planned_experiments=epm.planned_experiments,
        sequence_uuid=gen_uuid(),
        dummy=True,
        simulation=True,
    )


async def wait_for_glob(
    root: str, pattern: str, min_count: int = 1, timeout_s: float = 60.0
) -> list:
    """Poll ``root`` (rglob) for ``pattern`` until ``min_count`` matches land.

    Bridges a genuine async gap in the LEGACY finalize path: ``move_dir()``
    is fired via ``orch.aloop.create_task(...)`` (orch_lifecycle.py:120/213,
    active_finalizer.py:467) and never awaited by the code that flips
    ``loop_state`` to ``stopped`` — so :func:`wait_parked` can observe a
    parked loop seconds before the fire-and-forget ``move_dir()`` task
    finishes its ``retry_delay``-gated copy/remove/sync cycle
    (``helao/helpers/yml_tools.py``, unconditional ``asyncio.sleep`` even on
    first-try success) and the file actually lands in ``RUNS_FINISHED``.
    Callers needing on-disk artifacts must poll for them separately; do not
    assume "parked" implies "synced"."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    root_path = Path(root)
    hits: list = []
    while True:
        hits = list(root_path.rglob(pattern))
        if len(hits) >= min_count:
            return hits
        if asyncio.get_event_loop().time() >= deadline:
            raise TimeoutError(
                f"{pattern!r} under {root} never reached {min_count} match(es) "
                f"(found {len(hits)}) within {timeout_s}s"
            )
        await asyncio.sleep(0.5)


async def wait_parked(orch, timeout_s: float = 120.0) -> None:
    for _ in range(int(timeout_s / 0.25)):
        gsm = orch.globalstatusmodel
        if (
            gsm.loop_state == LoopStatus.stopped
            and not orch.action_dq
            and not orch.experiment_dq
            and not orch.sequence_dq
            and not gsm.active_dict
        ):
            return
        await asyncio.sleep(0.25)
    raise TimeoutError(
        f"group never parked: loop_state={orch.globalstatusmodel.loop_state} "
        f"dq=({len(orch.action_dq)},{len(orch.experiment_dq)},{len(orch.sequence_dq)})"
    )
