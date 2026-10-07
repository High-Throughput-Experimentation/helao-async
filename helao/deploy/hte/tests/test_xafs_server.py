"""XafsScanExec driven through the real ExecutorRunner against a fake driver.

No ActionHost is constructed (makeApp needs a loaded CONFIG): the session is a
minimal fake exposing only what the runner and the executor touch, the same
approach as ``helao/hexagon/tests/test_executor_runner.py``. The executor's
endpoint wiring (``makeApp``) is import-checked only.
"""

import asyncio
import io
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
)
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.core.models.sample import SolidSample
from helao.deploy.hte.servers.action import xafs_server
from helao.deploy.hte.servers.action.xafs_server import XafsScanExec
from helao.hexagon.app.executor_runner import ExecutorRunner

FCK = uuid4()
COLUMNS = ["Time", "Angle(deg)", "Energy(eV)"]
ALL_ROWS = [[float(i), 10.0 + i, 9000.0 + i] for i in range(4)]
GOOD_STATES = [("moving", 0), ("running", 2), ("running", 4), ("done", 4)]
STAGE_M = [[1.0, 0.0, 2.0], [0.0, 1.0, -3.0]]
REFS = {
    "xafs-std__solid__ref_1": {"name": "ZnO_film", "x_mm": 5.5, "y_mm": -6.5},
}


def ok(data=None):
    return DriverResponse(
        response=DriverResponseType.success, message="ok", data=data, status=DriverStatus.ok
    )


def fail(http_status=None):
    data = {"http_status": http_status, "detail": "x"} if http_status else None
    return DriverResponse(
        response=DriverResponseType.failed, message="bad", data=data, status=DriverStatus.error
    )


class FakeDriver:
    def __init__(
        self, states=GOOD_STATES, fail_state_call=None, start=None, est_total=1.0, transient=()
    ):
        self.transient = set(transient)  # 1-based scan_state calls failing without http_status
        self.states = list(states)
        self.fail_state_call = fail_state_call  # 1-based scan_state call that fails 404
        self.start_resp = start or ok({"scan_id": "s1"})
        self.est_total = est_total
        self.calls = []
        self.n_visible = 0
        self.last = self.states[-1][0]
        self.error = None

    def connect(self):
        return ok()

    def start_scan(self, **body):
        self.calls.append(("start_scan", body))
        return self.start_resp

    def scan_state(self, scan_id):
        n = sum(1 for c in self.calls if c[0] == "scan_state") + 1
        self.calls.append(("scan_state", scan_id))
        if self.fail_state_call == n:
            return fail(404)
        if n in self.transient:
            return fail()
        state, self.n_visible = self.states[min(n - 1, len(self.states) - 1)]
        return ok(
            {
                "state": state,
                "n_points": self.n_visible,
                "n_expected": 4,
                "elapsed": 1.0,
                "est_total": self.est_total,
                "exd_path": "/data/run/Zn_x_000_exd.csv.zip" if state == "done" else None,
                "error": "Traceback boom" if state == "error" else None,
            }
        )

    def rows_since(self, scan_id, since):
        self.calls.append(("rows_since", since))
        return ok({"columns": COLUMNS, "rows": ALL_ROWS[since : self.n_visible]})

    def fetch_mcas(self, scan_id):
        self.calls.append(("fetch_mcas",))
        buf = io.BytesIO()
        np.savez(buf, mcas=np.zeros((4, 3)))
        return ok({"npz": buf.getvalue()})

    def fetch_artifacts(self, scan_id):
        self.calls.append(("fetch_artifacts",))
        return ok(
            {
                "scan_def": {"advanced_calibration": {"k": 1}},
                "metadata": {"alpha_deg": 3.5},
            }
        )

    def stop(self):
        self.calls.append(("stop",))
        return ok()

    def names(self):
        return [c[0] for c in self.calls]


class FakeUnifiedDb:
    def __init__(self, xy=((10.0, 20.0),)):
        self.xy = [list(p) for p in xy]
        self.asked = []

    async def get_samples_xy(self, samples):
        self.asked.append(samples)
        return self.xy


class FakeSession:
    """What ExecutorRunner and XafsScanExec touch, and nothing else."""

    def __init__(self, tmp_path, driver, params, samples):
        self.driver = driver
        self.base = SimpleNamespace(
            local_action_task_queue=[],
            executors={},
            aloop=None,
            helaodirs=SimpleNamespace(save_root=str(tmp_path / "root")),
        )
        self.action = SimpleNamespace(
            action_uuid="u1",
            action_name="normal_scan",
            action_params=params,
            action_output_dir="out",
            manual_action=False,
            nonblocking=False,
            error_code=ErrorCodes.none,
            file_conn_keys=[FCK],
            samples_in=samples,
            files=[],
            append_action_status=lambda st: self.statuses.append(st),
        )
        self.statuses = []
        self.action_task = None
        self.action_loop_running = False
        self.manual_stop = False
        self.finished = False
        self.enqueued = []
        self.written = []
        self.tracked = []
        self.runner = ExecutorRunner(self)

    def enqueue_data_nowait(self, datamodel):
        self.enqueued.append(datamodel)

    async def write_file(self, output_str, file_type, filename=None, **kw):
        self.written.append((file_type, filename, output_str))

    async def track_file(self, file_type, file_path, samples, action=None):
        assert os.path.exists(file_path)
        self.tracked.append((file_type, file_path))

    async def finish(self):
        self.finished = True
        return self.action

    async def send_nonblocking_status(self, retry_limit=3):
        return None

    async def action_loop_task(self, executor):
        return await self.runner.action_loop_task(executor)

    def executor_done_callback(self, futr):
        return self.runner.executor_done_callback(futr)

    def rows(self):
        return [m.data[FCK] for m in self.enqueued]


def plate_sample(no=13983):
    return SolidSample(plate_id=1234, sample_no=no)


def ref_sample():
    return SolidSample(plate_id="ref", sample_no=1, machine_name="xafs-std")


def make(tmp_path, driver=None, samples=None, db=None, **over):
    params = {
        "scan_def": {"zone_defs": []},
        "element": "Zn",
        "run_use": "data",
        "xchanger_station": 2,
        "duration_scale": 1.0,
        "scan_index": 7,
        "save_dir": str(tmp_path / "run"),
    }
    params.update(over)
    driver = driver or FakeDriver()
    s = FakeSession(
        tmp_path, driver, params, [plate_sample()] if samples is None else samples
    )
    ex = XafsScanExec(
        active=s,
        oneoff=False,
        poll_rate=0.001,
        server_params={"platexy_to_stage": STAGE_M, "references": REFS},
        unified_db=db or FakeUnifiedDb(),
    )
    return s, ex, driver


async def run(s, ex):
    await asyncio.wait_for(s.runner.action_loop_task(ex), 10)


@pytest.mark.asyncio
async def test_rows_streamed_exact_columns(tmp_path):
    s, ex, d = make(tmp_path)
    await run(s, ex)
    rows = s.rows()
    assert len(rows) == 4
    assert all(list(r) == COLUMNS for r in rows)
    assert [r["Time"] for r in rows] == [0.0, 1.0, 2.0, 3.0]
    assert s.action.error_code == ErrorCodes.none and s.finished
    # request body: platexy (10, 20) + affine -> (12, 17)
    body = [c for c in d.calls if c[0] == "start_scan"][0][1]
    assert body["x_mm"] == 12.0 and body["y_mm"] == 17.0
    assert body["savename"] == "Zn_Scan0007_Sample13983_X12.000_Y17.000"
    assert body["xchanger_station"] == 2 and body["duration_scale"] == 1.0
    assert body["save_dir"] == str(tmp_path / "run")


@pytest.mark.asyncio
async def test_post_exec_files(tmp_path):
    s, ex, d = make(tmp_path)
    await run(s, ex)
    assert [t[0] for t in s.tracked] == ["xafsmca__npz_file"]
    path = s.tracked[0][1]
    assert path.startswith(os.path.join(str(tmp_path / "root"), "out"))
    assert np.load(path)["mcas"].shape == (4, 3)
    assert len(s.written) == 1
    ftype, _, text = s.written[0]
    assert ftype == "xafstrack__json_file" and json.loads(text) == {"k": 1}
    ap = s.action.action_params
    assert ap["exd_path"] == "/data/run/Zn_x_000_exd.csv.zip"
    assert ap["alpha_deg"] == 3.5


@pytest.mark.asyncio
async def test_poll_404_errors(tmp_path):
    d = FakeDriver(fail_state_call=2)
    s, ex, _ = make(tmp_path, driver=d)
    await run(s, ex)
    assert s.action.error_code == ErrorCodes.cmd_error
    assert d.names().count("scan_state") <= 2
    assert s.finished
    assert "fetch_mcas" not in d.names()


@pytest.mark.asyncio
async def test_sidecar_error_state(tmp_path):
    d = FakeDriver(states=[("running", 2), ("error", 2)])
    s, ex, _ = make(tmp_path, driver=d)
    await run(s, ex)
    assert s.action.error_code == ErrorCodes.cmd_error
    assert len(s.rows()) == 2  # rows kept
    assert "boom" in s.action.action_params["sidecar_error"]


@pytest.mark.asyncio
async def test_start_409_errored_no_poll(tmp_path):
    d = FakeDriver(start=fail(409))
    s, ex, _ = make(tmp_path, driver=d)
    await run(s, ex)
    assert s.action.error_code == ErrorCodes.cmd_error
    assert d.names() == ["start_scan"]
    assert s.rows() == [] and s.finished


@pytest.mark.asyncio
async def test_reference_sample_xy_from_params(tmp_path):
    db = FakeUnifiedDb()
    s, ex, d = make(
        tmp_path, samples=[ref_sample()], db=db, run_use="izero", element="Zn"
    )
    await run(s, ex)
    body = [c for c in d.calls if c[0] == "start_scan"][0][1]
    assert (body["x_mm"], body["y_mm"]) == (5.5, -6.5)  # no affine, no platemap
    assert body["savename"] == "Zn_IzeroRef_ZnO_film"
    assert db.asked == []


@pytest.mark.asyncio
async def test_unknown_sample_errors_no_sidecar_call(tmp_path):
    s, ex, d = make(tmp_path, samples=[SolidSample(plate_id="nope", sample_no=None)])
    await run(s, ex)
    assert s.action.error_code != ErrorCodes.none
    assert d.calls == []


@pytest.mark.asyncio
async def test_marker_written(tmp_path):
    s, ex, d = make(tmp_path)
    await run(s, ex)
    assert (tmp_path / "run" / ".helao_recorded").read_bytes() == b""


@pytest.mark.asyncio
async def test_manual_stop_stops_driver_and_finishes_clean(tmp_path):
    d = FakeDriver(states=[("running", 2), ("running", 2), ("stopped", 4)])
    s, ex, _ = make(tmp_path, driver=d)
    ex.poll_rate = 0.05
    task = asyncio.create_task(s.runner.action_loop_task(ex))
    await asyncio.sleep(0.02)
    s.runner.stop_action_task()
    await asyncio.wait_for(task, 10)
    assert "stop" in d.names()
    assert len(s.rows()) == 4  # drained to the final count
    assert s.action.error_code == ErrorCodes.none
    assert "fetch_mcas" in d.names()


@pytest.mark.asyncio
async def test_timeout_backstop_stops_and_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(xafs_server, "TIMEOUT_MARGIN_S", 0.0)
    d = FakeDriver(states=[("running", 0)], est_total=0.0)
    s, ex, _ = make(tmp_path, driver=d)
    await run(s, ex)
    assert "stop" in d.names()
    assert s.action.error_code == ErrorCodes.cmd_error


def test_make_app_exposed():
    assert callable(xafs_server.makeApp)


@pytest.mark.asyncio
async def test_pre_exec_exception_errors_no_start(tmp_path):
    class Boom(FakeUnifiedDb):
        async def get_samples_xy(self, samples):
            raise TypeError("bad platemap")

    s, ex, d = make(tmp_path, db=Boom())
    await run(s, ex)
    assert s.action.error_code == ErrorCodes.cmd_error
    assert d.calls == [] and s.finished


@pytest.mark.asyncio
async def test_post_exec_exception_errors_and_finishes(tmp_path):
    d = FakeDriver()
    d.fetch_artifacts = lambda sid: ok({"scan_def": {}})  # no "metadata"
    s, ex, _ = make(tmp_path, driver=d)
    await run(s, ex)
    assert s.action.error_code == ErrorCodes.cmd_error
    assert HloStatus.errored in s.statuses and s.finished


@pytest.mark.asyncio
async def test_transient_poll_failures_tolerated(tmp_path):
    d = FakeDriver(transient=(2, 3))
    s, ex, _ = make(tmp_path, driver=d)
    await run(s, ex)
    assert s.action.error_code == ErrorCodes.none
    assert len(s.rows()) == 4
    assert "stop" not in d.names()


@pytest.mark.asyncio
async def test_three_consecutive_failures_stop_and_error(tmp_path):
    d = FakeDriver(transient=(2, 3, 4))
    s, ex, _ = make(tmp_path, driver=d)
    await run(s, ex)
    assert "stop" in d.names()
    assert s.action.error_code == ErrorCodes.cmd_error


@pytest.mark.asyncio
@pytest.mark.parametrize("idx", [-1, 10000, "3"])
async def test_scan_index_out_of_range(tmp_path, idx):
    s, ex, d = make(tmp_path, scan_index=idx)
    await run(s, ex)
    assert s.action.error_code == ErrorCodes.cmd_error
    assert d.calls == []


@pytest.mark.asyncio
async def test_final_state_recorded(tmp_path):
    s, ex, _ = make(tmp_path)
    await run(s, ex)
    ap = s.action.action_params
    assert (ap["scan_state"], ap["n_points"], ap["n_expected"]) == ("done", 4, 4)


class StubApp:
    def __init__(self, driver, tmp_path):
        self.server_params = {}
        self.driver = driver
        self.base = SimpleNamespace(helaodirs=SimpleNamespace(db_root=str(tmp_path)))
        self.eps = {}

    def action(self):
        def deco(f):
            self.eps[f.__name__] = f
            return f

        return deco


class EpActive:
    def __init__(self, params, samples=()):
        self.action = SimpleNamespace(
            action_params=params,
            action_name="ep", action_uuid="u",
            samples_in=list(samples),
            file_conn_keys=[FCK],
            run_use=None,
            error_code=ErrorCodes.none,
            append_action_status=lambda st: None,
        )
        self.driver = None
        self.dflt = []
        self.executor = None

    def finish_hlo_header(self, **kw):
        pass

    def get_realtime_nowait(self):
        return 0

    def start_executor(self, ex):
        self.executor = ex
        return {}

    async def enqueue_data_dflt(self, datadict):
        self.dflt.append(datadict)

    async def finish(self):
        return SimpleNamespace(as_dict=lambda: {"error": self.action.error_code})


class EpCtx:
    def __init__(self, active):
        self.active = active
        self.action = active.action

    async def begin(self, **kw):
        return self.active


async def make_eps(tmp_path, driver):
    app = StubApp(driver, tmp_path)
    await xafs_server.xafs_dyn_endpoints(app)
    return app.eps


@pytest.mark.asyncio
async def test_normal_scan_sets_action_run_use(tmp_path):
    from helao.core.models.run_use import RunUse

    eps = await make_eps(tmp_path, FakeDriver())
    params = {"scan_def": {}, "run_use": "izero"}
    a = EpActive(params, [ref_sample()])
    await eps["normal_scan"](EpCtx(a))
    assert a.action.run_use == RunUse.izero
    assert a.executor is not None


@pytest.mark.asyncio
async def test_status_returns_health_and_hw(tmp_path):
    d = FakeDriver()
    d.get_status = lambda: ok({"state": None})
    d.hw_status = lambda: ok({"mono_calibrated": True})
    eps = await make_eps(tmp_path, d)
    a = EpActive({})
    await eps["status"](EpCtx(a))
    assert a.dflt[0]["status"] == {"health": {"state": None}, "hw": {"mono_calibrated": True}}
    assert a.action.error_code == ErrorCodes.none


@pytest.mark.asyncio
async def test_calibrate_timeout_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(xafs_server, "CALIBRATE_POLL_S", 0.001)
    d = FakeDriver()
    d.calibrate = lambda devices: ok({"job_id": "j"})
    d.job_state = lambda jid: ok({"state": "running", "error": None})
    eps = await make_eps(tmp_path, d)
    a = EpActive({"devices": ["mono"], "timeout": 0.05})
    await eps["calibrate"](EpCtx(a))
    assert a.action.error_code == ErrorCodes.cmd_error
    assert "timeout" in a.dflt[0]["message"]
