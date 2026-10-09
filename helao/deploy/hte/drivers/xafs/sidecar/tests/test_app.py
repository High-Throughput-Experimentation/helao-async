"""Python 3.9 sim env: sidecar FastAPI app over fakes."""

import os
import subprocess
import time
from io import BytesIO

import numpy as np
import pytest
from fastapi.testclient import TestClient

from helao.deploy.hte.drivers.xafs.sidecar import xafs_sidecar


def scan_def(n_points=4):
    return {
        "type": "NormalScan",
        "element": "Zn",
        "measurement_mode": "XAFS_Fluorescence",
        "crystal2d": "Si(5,5,3)",
        "beta_offset": 0,
        "theta_offset": 0,
        "analyzer_radius": 500,
        "alpha": 0,
        "ROI": {"roi_bragg": 80, "roi_min": 800, "roi_max": 1000},
        "zone_defs": [
            {
                "mode": "constant_step",
                "energy_min": 9600,
                "energy_max": 9600 + 5 * n_points,
                "energy_step": 5,
                "duration": 0.01,
            }
        ],
    }


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lock = str(tmp_path / "sidecar.lock")
    exits = []
    app = xafs_sidecar.create_app(
        True, lock, str(tmp_path), exit_fn=lambda: exits.append(1)
    )
    (tmp_path / "save").mkdir()
    return TestClient(app), app.state.sim, lock, str(tmp_path / "save"), exits


@pytest.fixture
def hw(ctx):
    assert ctx[0].post("/initialize", json={}).status_code == 200
    return ctx


def body(save_dir, **kw):
    d = {
        "scan_def": scan_def(),
        "x_mm": 1.0,
        "y_mm": 2.0,
        "xchanger_station": 1,
        "savename": "Zn_Scan0000_Sample1_X1.000_Y2.000",
        "save_dir": save_dir,
        "duration_scale": 1.0,
    }
    d.update(kw)
    return d


def wait_done(c, sid, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = c.get("/scans/" + sid).json()
        if s["state"] in ("done", "stopped", "error"):
            return s
        time.sleep(0.02)
    raise AssertionError(s)


def test_health_no_hw(ctx):
    c = ctx[0]
    j = c.get("/health").json()
    assert j["hw_initialized"] is False and j["simulate"] is True
    assert j["python"].startswith("3.9")


def test_initialize_then_status(ctx):
    c = ctx[0]
    flags = {k: True for k in ("mono", "ketek", "wafer_stage", "xchanger", "proto")}
    r = c.post("/initialize", json=flags)
    assert r.status_code == 200, r.text
    assert all(r.json()[k] == "ok" for k in flags), r.json()
    assert c.post("/initialize", json=flags).status_code == 200  # idempotent on own pid
    assert c.get("/health").json()["hw_initialized"] is True
    st = c.get("/status").json()
    for k in ("mono_calibrated", "wafer_xy", "xchanger_station", "proto", "scan_id"):
        assert k in st


def test_initialize_lock_held(ctx):
    c, h, lock = ctx[0], ctx[1], ctx[2]
    calls = []
    h.mono.initialize = lambda: calls.append(1)
    p = subprocess.Popen(["sleep", "30"])
    try:
        with open(lock, "w", encoding="utf-8") as f:
            f.write(str(p.pid))
        r = c.post("/initialize", json={})
        assert r.status_code == 423
        assert r.json()["pid"] == p.pid
        assert not calls
    finally:
        p.kill()
        p.wait()


def test_stale_lock_replaced(ctx):
    c, lock = ctx[0], ctx[2]
    p = subprocess.Popen(["true"])
    p.wait()
    with open(lock, "w", encoding="utf-8") as f:
        f.write(str(p.pid))
    assert c.post("/initialize", json={}).status_code == 200
    assert open(lock, encoding="utf-8").read().strip() == str(os.getpid())


def test_scan_roundtrip(hw):
    c, save_dir = hw[0], hw[3]
    r = c.post("/scans", json=body(save_dir))
    assert r.status_code == 200, r.text
    sid = r.json()["scan_id"]
    assert wait_done(c, sid)["state"] == "done"
    rows = c.get("/scans/%s/rows?since=0" % sid).json()
    assert len(rows["rows"]) == 4 and rows["columns"][0] == "Time"
    m = c.get("/scans/%s/mcas" % sid)
    assert m.headers["content-type"] == "application/octet-stream"
    assert "mcas" in np.load(BytesIO(m.content)).files
    assert "scan_def" in c.get("/scans/%s/artifacts" % sid).json()


def test_mcas_before_done_409(hw):
    c, h, save_dir = hw[0], hw[1], hw[3]
    h.wafer_stage.move_delay = 0.5
    sid = c.post("/scans", json=body(save_dir)).json()["scan_id"]
    assert c.get("/scans/%s/mcas" % sid).status_code == 409
    c.post("/scans/%s/stop" % sid)
    wait_done(c, sid)


def test_scan_409_interlock(hw):
    c, h, save_dir = hw[0], hw[1], hw[3]
    h.proto.shutter = "Closed"
    r = c.post("/scans", json=body(save_dir))
    assert r.status_code == 409
    assert "shutter" in r.json()["detail"]


def test_scan_409_busy(hw):
    c, h, save_dir = hw[0], hw[1], hw[3]
    h.wafer_stage.move_delay = 0.5
    sid = c.post("/scans", json=body(save_dir)).json()["scan_id"]
    assert c.post("/scans", json=body(save_dir)).status_code == 409
    assert c.get("/status").json()["scan_id"] == sid
    c.post("/scans/%s/stop" % sid)
    wait_done(c, sid)


def test_unknown_scan_404(ctx):
    c = ctx[0]
    for p in ("", "/rows?since=0", "/mcas", "/artifacts"):
        assert c.get("/scans/nope" + p).status_code == 404
    assert c.post("/scans/nope/stop").status_code == 404


def test_stop_endpoint(hw):
    c, h, save_dir = hw[0], hw[1], hw[3]
    h.mono.move_delay = 0.3
    sid = c.post("/scans", json=body(save_dir)).json()["scan_id"]
    for _ in range(200):
        if c.get("/scans/" + sid).json()["state"] == "running":
            break
        time.sleep(0.01)
    assert c.post("/scans/%s/stop" % sid).status_code == 200
    assert wait_done(c, sid)["state"] == "stopped"


def test_xray_shutter_close(hw):
    c = hw[0]
    r = c.post("/xray", json={"shutter": "close"})
    assert r.status_code == 200, r.text
    assert c.get("/status").json()["proto"]["shutter"] == "Closed"
    assert c.post("/xray", json={"kv": 40, "ma": 0.5}).json()["kv"] == 40
    assert c.post("/xray", json={"off": True}).json()["kv"] == 0


def test_calibrate_job(hw):
    c = hw[0]
    jid = c.post("/calibrate", json={"devices": ["mono"]}).json()["job_id"]
    for _ in range(200):
        j = c.get("/jobs/" + jid).json()
        if j["state"] != "running":
            break
        time.sleep(0.02)
    assert j["state"] == "done", j
    assert c.get("/jobs/nope").status_code == 404


def test_shutdown_releases_lock(hw):
    c, h, lock, exits = hw[0], hw[1], hw[2], hw[4]
    assert os.path.exists(lock)
    assert c.post("/shutdown").status_code == 200
    assert not os.path.exists(lock)
    assert h.proto.shutter == "Closed"
    time.sleep(0.5)
    assert exits


def test_shutdown_keeps_foreign_lock(ctx):
    c, lock = ctx[0], ctx[2]
    p = subprocess.Popen(["sleep", "30"])
    try:
        with open(lock, "w", encoding="utf-8") as f:
            f.write(str(p.pid))
        assert c.post("/shutdown").status_code == 200
        assert open(lock, encoding="utf-8").read() == str(p.pid)
        assert ctx[1].proto.shutter == "Open"
    finally:
        p.kill()
        p.wait()


def test_shutdown_waits_for_scan(hw):
    c, h, save_dir = hw[0], hw[1], hw[3]
    h.mono.move_delay = 0.2
    sid = c.post("/scans", json=body(save_dir)).json()["scan_id"]
    assert c.post("/shutdown").status_code == 200
    assert c.get("/scans/" + sid).json()["state"] not in (
        "queued",
        "moving",
        "running",
        "saving",
    )


def test_logging_survives_easyxafs_import(ctx):
    import logging
    import importlib
    import easyxafs.logging_setup as ls

    importlib.reload(ls)  # what a late first import would do: clears root handlers
    xafs_sidecar.create_app(True, ctx[2], str(ctx[3]) + "_x", exit_fn=None)
    assert any(getattr(x, "_xafs_sidecar", False) for x in logging.getLogger().handlers)


def test_status_has_bragg(hw):
    assert set(hw[0].get("/status").json()["mono_bragg"]) == {
        "Beta",
        "Detector",
        "Rho",
        "Theta",
    }


def test_hw_routes_423_without_lock(ctx):
    c, save_dir = ctx[0], ctx[3]
    assert c.post("/xray", json={"shutter": "close"}).status_code == 423
    assert c.post("/scans", json=body(save_dir)).status_code == 423
    assert c.post("/calibrate", json={"devices": ["mono"]}).status_code == 423


def test_bad_request_422(hw):
    c = hw[0]
    assert c.post("/xray", json={"shutter": "ajar"}).status_code == 422
    assert c.post("/calibrate", json={"devices": ["toaster"]}).status_code == 422


def test_calibrate_vs_scan_guards(hw):
    c, h, save_dir = hw[0], hw[1], hw[3]
    import threading

    gate = threading.Event()
    h.mono.calibrate_all = lambda: gate.wait(10)
    jid = c.post("/calibrate", json={"devices": ["mono"]}).json()["job_id"]
    assert c.post("/scans", json=body(save_dir)).status_code == 409
    assert c.post("/calibrate", json={"devices": ["mono"]}).status_code == 409
    gate.set()
    for _ in range(200):
        if c.get("/jobs/" + jid).json()["state"] != "running":
            break
        time.sleep(0.02)
    h.wafer_stage.move_delay = 0.5
    sid = c.post("/scans", json=body(save_dir)).json()["scan_id"]
    assert c.post("/calibrate", json={"devices": ["mono"]}).status_code == 409
    c.post("/scans/%s/stop" % sid)
    wait_done(c, sid)


def test_scan_roi_element(hw):
    c, save_dir = hw[0], hw[3]
    r = c.post("/scans", json=body(save_dir, roi_element="Fe"))
    assert r.status_code == 200, r.text
    assert wait_done(c, r.json()["scan_id"])["state"] == "done"
    r = c.post("/scans", json=body(save_dir, roi_element="Xx"))
    assert r.status_code == 409 and "Xx" in r.json()["detail"]


def test_unknown_field_422(hw):
    c, save_dir = hw[0], hw[3]
    assert c.post("/scans", json=body(save_dir, bogus=1)).status_code == 422
    assert c.post("/initialize", json={"bogus": True}).status_code == 422
    assert c.post("/calibrate", json={"devices": ["mono"], "x": 1}).status_code == 422
    assert c.post("/xray", json={"kv": 1, "x": 1}).status_code == 422


def test_calibrate_during_scan_start_interlock_window_409(hw):
    import threading

    c, h, save_dir = hw[0], hw[1], hw[3]
    real = h.proto.readback_kv_ma
    entered = threading.Event()

    def slow():
        entered.set()
        time.sleep(0.6)  # widen the check-and-start window inside runner.start
        return real()

    h.proto.readback_kv_ma = slow
    out = {}
    t = threading.Thread(
        target=lambda: out.update(r=c.post("/scans", json=body(save_dir)))
    )
    t.start()
    assert entered.wait(5)
    cal = c.post("/calibrate", json={"devices": ["mono"]})
    t.join()
    assert out["r"].status_code == 200, out["r"].text
    assert cal.status_code == 409, cal.text
    h.proto.readback_kv_ma = real
    c.post("/scans/%s/stop" % out["r"].json()["scan_id"])
    wait_done(c, out["r"].json()["scan_id"])


def test_scan_while_calibrate_running_409(hw):
    import threading

    c, h, save_dir = hw[0], hw[1], hw[3]
    gate = threading.Event()
    h.mono.calibrate_all = lambda: gate.wait(10)
    jid = c.post("/calibrate", json={"devices": ["mono"]}).json()["job_id"]
    try:
        assert c.post("/scans", json=body(save_dir)).status_code == 409
    finally:
        gate.set()
    for _ in range(200):
        if c.get("/jobs/" + jid).json()["state"] != "running":
            break
        time.sleep(0.02)


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_calibrate_409_while_watchdog_hung_thread_alive(ctx, monkeypatch):
    from helao.deploy.hte.drivers.xafs.sidecar.runner import ScanRunner

    monkeypatch.setattr(
        xafs_sidecar, "ScanRunner", lambda: ScanRunner(watchdog_margin_s=0.3)
    )
    app = xafs_sidecar.create_app(True, ctx[2], ctx[3] + "_x", exit_fn=None)
    c, h, save_dir = TestClient(app), app.state.sim, ctx[3]
    assert c.post("/initialize", json={}).status_code == 200
    h.ketek.hang = (
        True  # hangs scan.start(): watchdog errors the record, thread stays alive
    )
    try:
        sid = c.post("/scans", json=body(save_dir)).json()["scan_id"]
        assert wait_done(c, sid)["state"] == "error"
        assert c.post("/calibrate", json={"devices": ["mono"]}).status_code == 409
    finally:
        h.ketek.hang = False
    t0 = time.time()
    while c.post("/calibrate", json={"devices": ["mono"]}).status_code == 409:
        assert time.time() - t0 < 15
        time.sleep(0.05)


def test_shutdown_waits_for_calibrate_job(hw):
    import threading

    c, h = hw[0], hw[1]
    gate = threading.Event()
    h.mono.calibrate_all = lambda: gate.wait(10)
    jid = c.post("/calibrate", json={"devices": ["mono"]}).json()["job_id"]
    threading.Timer(0.5, gate.set).start()
    t0 = time.time()
    assert c.post("/shutdown").status_code == 200
    assert time.time() - t0 >= 0.4
    assert c.get("/jobs/" + jid).json()["state"] != "running"
