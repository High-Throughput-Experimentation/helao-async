"""C1 gate: production sync runs on ``NativeSyncer`` through the wired ``SyncPort``.

What each test can catch that the others cannot:

* the port surface is the measured one, and the adapter delegates every member
  with its arguments intact;
* the orchestrator's only syncer use (``to_s3``, twice) goes through
  ``orch.hexagon_wiring.sync`` -- the dispatch golden master stubs ``to_s3`` and
  both call sites swallow every exception, so a broken route is silent there;
* the SYNC server and the sim DB server bind the port at startup, only when
  ``app.driver`` exists, and their routes read the port at call time.
"""

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir
from helao.hexagon.adapters.native.native_syncer import NativeSyncer
from helao.hexagon.adapters.native.sync_adapter import NativeSyncAdapter
from helao.hexagon.ports.sync import SyncPort
from helao.hexagon.tests.sync_fixtures import teardown_driver

PORT_MEMBERS = {
    "enqueue_yml",
    "release_quarantine",
    "list_pending",
    "finish_pending",
    "reset_sync",
    "write_off",
    "quarantined",
    "running_tasks",
    "n_queue",
    "has_pending_work",
    "to_s3",
}

PARAMS = {"aws_bucket": "helao-sim", "max_tasks": 1}


@pytest.fixture(autouse=True)
def _hermetic_aws(monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)


@pytest.fixture(autouse=True)
def _port_already_bound(monkeypatch):
    """No test here binds a port; keep any startup sweep from waiting it out."""
    from helao.deploy.hte.servers.action import sync_server

    async def bound(*a, **k):
        return True

    monkeypatch.setattr(sync_server, "wait_until_listening", bound)


async def _native_syncer(tmp_path):
    host = SimpleNamespace(
        server_cfg={"params": dict(PARAMS)},
        world_cfg={"servers": {"SYNC": {"params": dict(PARAMS)}}},
        helaodirs=HelaoDirs(
            root=Path(tmp_path),
            save_root=Path(tmp_path) / RunDir.ACTIVE.value,
            process_root=Path(tmp_path) / "PROCESSES",
        ),
    )
    return NativeSyncer(host)  # type: ignore[arg-type]  # duck-typed SyncerHost


# --------------------------------------------------------------------------
# 1 + 2: the port and its adapter
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_port_surface_is_the_measured_one(tmp_path):
    assert {m for m in dir(SyncPort) if not m.startswith("_")} == PORT_MEMBERS
    drv = await _native_syncer(tmp_path)
    try:
        assert isinstance(NativeSyncAdapter(drv), SyncPort)
    finally:
        await teardown_driver(drv)


class _RecordingDriver:
    """Records every call the adapter delegates, with its exact arguments."""

    def __init__(self):
        self.calls = []
        self.running_tasks = {"t": object()}
        self.task_queue = SimpleNamespace(qsize=lambda: 7)

    async def enqueue_yml(self, upath, rank=0, rank_limit=-5):
        self.calls.append(("enqueue_yml", upath, rank, rank_limit))

    def release_quarantine(self, yml_path):
        self.calls.append(("release_quarantine", yml_path))
        return True

    def list_pending(self, omit_manual_exps=True):
        self.calls.append(("list_pending", omit_manual_exps))
        return ["p"]

    async def finish_pending(self, omit_manual_exps=True, actions_first=False):
        self.calls.append(("finish_pending", omit_manual_exps, actions_first))
        return ["f"]

    def reset_sync(self, sync_path):
        self.calls.append(("reset_sync", sync_path))
        return True

    async def write_off(self, yml_path, reason, operator):
        self.calls.append(("write_off", yml_path, reason, operator))
        return {"ok": True}

    def quarantined(self):
        self.calls.append(("quarantined",))
        return ["q"]

    def has_pending_work(self):
        self.calls.append(("has_pending_work",))
        return True

    async def to_s3(self, msg, target, retries=5, compress=False):
        self.calls.append(("to_s3", msg, target, retries, compress))
        return True


@pytest.mark.asyncio
async def test_adapter_delegates_every_member():
    drv = _RecordingDriver()
    port = NativeSyncAdapter(drv)  # type: ignore[arg-type]

    await port.enqueue_yml("x-act.yml", 2, rank_limit=-3)
    assert port.release_quarantine("r.yml") is True
    assert port.list_pending(omit_manual_exps=False) == ["p"]
    assert await port.finish_pending(omit_manual_exps=False, actions_first=True) == [
        "f"
    ]
    assert port.reset_sync("zz") is True
    assert await port.write_off("w.yml", "why", "op") == {"ok": True}
    assert port.quarantined() == ["q"]
    assert port.running_tasks() is drv.running_tasks
    assert port.n_queue() == 7
    assert port.has_pending_work() is True
    assert await port.to_s3({"a": 1}, "k", retries=2, compress=True) is True

    assert drv.calls == [
        ("enqueue_yml", "x-act.yml", 2, -3),
        ("release_quarantine", "r.yml"),
        ("list_pending", False),
        ("finish_pending", False, True),
        ("reset_sync", "zz"),
        ("write_off", "w.yml", "why", "op"),
        ("quarantined",),
        ("has_pending_work",),
        ("to_s3", {"a": 1}, "k", 2, True),
    ]
    # these four stay plain functions so their ``def`` routes keep running in
    # FastAPI's threadpool; an async wrapper would block the loop on the unzip
    for name in ("reset_sync", "list_pending", "release_quarantine", "quarantined"):
        assert not inspect.iscoroutinefunction(getattr(port, name)), name


# --------------------------------------------------------------------------
# 3: the orchestrator's only C1 gate
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orch_to_s3_goes_through_the_port(tmp_path):
    from helao.core.tests.test_orch_dispatch_golden_master import (
        _install_recording_stubs,
        _make_orch,
    )
    from helao.helpers.premodels import Experiment

    orch = _make_orch(tmp_path)
    _install_recording_stubs(orch, [])
    calls = []

    async def _to_s3(payload, key):
        calls.append(key)

    orch.hexagon_wiring.sync = SimpleNamespace(to_s3=_to_s3)  # type: ignore[assignment]
    exp = Experiment(experiment_name="direct_exp")
    exp.init_exp()
    exp.orchestrator = orch.server
    orch.active_experiment = exp

    await orch.dispatch_runner._upload_exp_meta_s3()

    assert calls == [f"experiment/{exp.experiment_uuid}.json"]


# --------------------------------------------------------------------------
# 4 + 5 + 6: the servers bind the port, guarded, and read it at call time
# --------------------------------------------------------------------------


class _RecordingPort:
    def __init__(self):
        self.calls = []

    def release_quarantine(self, yml_path):
        self.calls.append(("release_quarantine", yml_path))
        return False

    async def enqueue_yml(self, upath, rank=0, rank_limit=-5):
        self.calls.append(("enqueue_yml", upath, rank))

    async def finish_pending(self, omit_manual_exps=True, actions_first=False):
        self.calls.append(("finish_pending", actions_first))
        return []


def _install_config(tmp_path, monkeypatch, fast):
    from helao.helpers import config_loader

    (tmp_path / "LOGS").mkdir(exist_ok=True)
    monkeypatch.setattr(
        config_loader,
        "CONFIG",
        {
            "root": str(tmp_path),
            "dummy": True,
            "simulation": True,
            "servers": {
                "SYNC": {
                    "host": "127.0.0.1",
                    "port": 8910,
                    "group": "action",
                    "fast": fast,
                    "params": dict(PARAMS),
                }
            },
        },
    )


def _make_hte(tmp_path, monkeypatch):
    from helao.deploy.hte.servers.action import sync_server

    _install_config(tmp_path, monkeypatch, "sync_server")
    return sync_server.makeApp("SYNC")


def _make_sim(tmp_path, monkeypatch):
    from helao.deploy.test.servers.action import sim_db_server

    _install_config(tmp_path, monkeypatch, "sim_db_server")
    return sim_db_server.makeApp("SYNC")


def _handler(app, name):
    return next(h for h in app.router.on_startup if h.__name__ == name)


def _route(app, path):
    return next(r.endpoint for r in app.routes if getattr(r, "path", None) == path)


async def _started(app):
    """Run only the host's own startup (builds ``app.driver``) and the bind."""
    _handler(app, "startup_event")()
    _handler(app, "_bind_sync_port")()


async def _teardown(app):
    await teardown_driver(app.driver)
    await app.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("make", [_make_hte, _make_sim], ids=["hte", "sim"])
async def test_server_routes_use_the_port(make, tmp_path, monkeypatch):
    app = make(tmp_path, monkeypatch)
    await _started(app)
    try:
        assert isinstance(app.hexagon_wiring.sync, NativeSyncAdapter)
        assert app.hexagon_wiring.sync._syncer is app.driver

        # replaced AFTER startup: it only reaches the route if the route reads
        # the port at call time rather than capturing it in makeApp
        rec = _RecordingPort()
        app.hexagon_wiring.sync = rec  # type: ignore[assignment]
        assert await _route(app, "/finish_yml")("a-act.yml") == "a-act.yml"
        assert ("enqueue_yml", "a-act.yml", 0) in rec.calls
        await _route(app, "/finish_pending")(actions_first=False)
        assert ("finish_pending", False) in rec.calls
    finally:
        app.hexagon_wiring.sync = None
        await _teardown(app)


@pytest.mark.asyncio
async def test_hte_finish_yml_releases_quarantine_first(tmp_path, monkeypatch):
    app = _make_hte(tmp_path, monkeypatch)
    await _started(app)
    try:
        rec = _RecordingPort()
        app.hexagon_wiring.sync = rec  # type: ignore[assignment]
        await _route(app, "/finish_yml")("a-act.yml")
        assert [c[0] for c in rec.calls] == ["release_quarantine", "enqueue_yml"]
    finally:
        app.hexagon_wiring.sync = None
        await _teardown(app)


@pytest.mark.asyncio
async def test_hte_no_driver_stays_unbound(tmp_path, monkeypatch):
    """No driver (startup never built one): the port stays ``None`` and
    ``/hotreload_busy`` still answers "not busy" rather than reporting a raising
    hook as busy."""
    app = _make_hte(tmp_path, monkeypatch)
    assert app.driver is None
    _handler(app, "_wire_hotreload_busy")()
    _handler(app, "_bind_sync_port")()

    assert app.hexagon_wiring.sync is None
    assert _route(app, "/hotreload_busy")() == {"busy": False}


@pytest.mark.asyncio
async def test_sim_no_driver_stays_unbound(tmp_path, monkeypatch):
    app = _make_sim(tmp_path, monkeypatch)
    assert app.driver is None
    _handler(app, "_bind_sync_port")()

    assert app.hexagon_wiring.sync is None


@pytest.mark.asyncio
async def test_hte_hotreload_busy_reads_the_port(tmp_path, monkeypatch):
    app = _make_hte(tmp_path, monkeypatch)
    await _started(app)
    _handler(app, "_wire_hotreload_busy")()
    try:
        app.hexagon_wiring.sync = SimpleNamespace(has_pending_work=lambda: True)  # type: ignore[assignment]
        assert _route(app, "/hotreload_busy")() == {"busy": True}
        app.hexagon_wiring.sync = SimpleNamespace(has_pending_work=lambda: False)  # type: ignore[assignment]
        assert _route(app, "/hotreload_busy")() == {"busy": False}
    finally:
        app.hexagon_wiring.sync = None
        await _teardown(app)


# --------------------------------------------------------------------------
# 8: the analysis driver rides the native to_s3
# --------------------------------------------------------------------------


def test_analysis_syncer_rides_native_to_s3():
    from helao.core.drivers.data.analysis_driver import AnalysisSyncer
    from helao.hexagon.adapters.native.sync_driver import SyncDriver

    assert issubclass(AnalysisSyncer, NativeSyncer)
    assert AnalysisSyncer.to_s3 is SyncDriver.to_s3
