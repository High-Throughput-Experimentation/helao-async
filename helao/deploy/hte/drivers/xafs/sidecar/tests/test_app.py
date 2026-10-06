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
        "type": "NormalScan", "element": "Zn", "measurement_mode": "XAFS_Fluorescence",
        "crystal2d": "Si(5,5,3)", "beta_offset": 0, "theta_offset": 0,
        "analyzer_radius": 500, "alpha": 0,
        "ROI": {"roi_bragg": 80, "roi_min": 800, "roi_max": 1000},
        "zone_defs": [{"mode": "constant_step", "energy_min": 9600,
                       "energy_max": 9600 + 5 * n_points, "energy_step": 5,
                       "duration": 0.01}],
    }


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lock = str(tmp_path / "sidecar.lock")
    exits = []
    app = xafs_sidecar.create_app(True, lock, str(tmp_path), exit_fn=lambda: exits.append(1))
    (tmp_path / "save").mkdir()
    return TestClient(app), app.state.sim, lock, str(tmp_path / "save"), exits


def body(save_dir, **kw):
    d = {"scan_def": scan_def(), "x_mm": 1.0, "y_mm": 2.0, "xchanger_station": 1,
         "savename": "Zn_Scan0000_Sample1_X1.000_Y2.000", "save_dir": save_dir,
         "duration_scale": 1.0}
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
        with open(lock, "w") as f:
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
    with open(lock, "w") as f:
        f.write(str(p.pid))
    assert c.post("/initialize", json={}).status_code == 200
    assert open(lock).read().strip() == str(os.getpid())


def test_scan_roundtrip(ctx):
    c, save_dir = ctx[0], ctx[3]
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


def test_mcas_before_done_409(ctx):
    c, h, save_dir = ctx[0], ctx[1], ctx[3]
    h.wafer_stage.move_delay = 0.5
    sid = c.post("/scans", json=body(save_dir)).json()["scan_id"]
    assert c.get("/scans/%s/mcas" % sid).status_code == 409
    c.post("/scans/%s/stop" % sid)
    wait_done(c, sid)


def test_scan_409_interlock(ctx):
    c, h, save_dir = ctx[0], ctx[1], ctx[3]
    h.proto.shutter = "Closed"
    r = c.post("/scans", json=body(save_dir))
    assert r.status_code == 409
    assert "shutter" in r.json()["detail"]


def test_scan_409_busy(ctx):
    c, h, save_dir = ctx[0], ctx[1], ctx[3]
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


def test_stop_endpoint(ctx):
    c, h, save_dir = ctx[0], ctx[1], ctx[3]
    h.wafer_stage.move_delay = 0.3
    sid = c.post("/scans", json=body(save_dir)).json()["scan_id"]
    assert c.post("/scans/%s/stop" % sid).status_code == 200
    assert wait_done(c, sid)["state"] in ("stopped", "done")


def test_xray_shutter_close(ctx):
    c = ctx[0]
    r = c.post("/xray", json={"shutter": "close"})
    assert r.status_code == 200, r.text
    assert c.get("/status").json()["proto"]["shutter"] == "Closed"
    assert c.post("/xray", json={"kv": 40, "ma": 0.5}).json()["kv"] == 40
    assert c.post("/xray", json={"off": True}).json()["kv"] == 0


def test_calibrate_job(ctx):
    c = ctx[0]
    jid = c.post("/calibrate", json={"devices": ["mono"]}).json()["job_id"]
    for _ in range(200):
        j = c.get("/jobs/" + jid).json()
        if j["state"] != "running":
            break
        time.sleep(0.02)
    assert j["state"] == "done", j
    assert c.get("/jobs/nope").status_code == 404


def test_shutdown_releases_lock(ctx):
    c, h, lock, exits = ctx[0], ctx[1], ctx[2], ctx[4]
    c.post("/initialize", json={})
    assert os.path.exists(lock)
    assert c.post("/shutdown").status_code == 200
    assert not os.path.exists(lock)
    assert h.proto.shutter == "Closed"
    time.sleep(0.5)
    assert exits
