"""Python 3.9 sim env: ScanRunner drives the vendor easyxafs scan loop on fakes."""
import re
import time
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest

from helao.deploy.hte.drivers.xafs.sidecar import sim_hw
from helao.deploy.hte.drivers.xafs.sidecar.runner import (
    BusyError,
    InterlockError,
    ScanRunner,
)

NAME_RE = re.compile(r"^Zn_Scan\d{4}_Sample\d+_X-?\d+\.\d{3}_Y-?\d+\.\d{3}_\d{3}_exd\.csv\.zip$")
SAVENAME = "Zn_Scan0000_Sample1_X1.000_Y2.000"


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
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = sim_hw.install_sim(str(tmp_path))
    save_dir = tmp_path / "save"
    save_dir.mkdir()
    return h, str(save_dir)


def go(runner, env, n_points=4, x=1.0, y=2.0, station=None):
    h, save_dir = env
    return runner.start(scan_def(n_points), x, y, station, SAVENAME, save_dir)


def wait(runner, sid, states=("done", "stopped", "error"), timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = runner.state(sid)
        if s["state"] in states:
            return s
        time.sleep(0.01)
    raise AssertionError("timeout, last state %r" % (runner.state(sid),))


def test_full_scan_done(env):
    r = ScanRunner()
    sid = go(r, env)
    s = wait(r, sid)
    assert s["state"] == "done", s
    assert s["n_points"] == 4 and s["n_expected"] == 4
    assert len(r.rows(sid, 0)["rows"]) == 4
    assert Path(s["exd_path"]).is_file()
    assert NAME_RE.match(Path(s["exd_path"]).name)


def test_rows_since(env):
    r = ScanRunner()
    sid = go(r, env)
    wait(r, sid)
    out = r.rows(sid, 2)
    assert len(out["rows"]) == 2
    assert out["columns"][0] == "Time" and "MCA" not in out["columns"]
    assert out["columns"][-4:] == ["Beta_encoder", "Detector_encoder", "Rho_encoder", "Theta_encoder"]
    assert len(out["rows"][0]) == len(out["columns"])
    assert all(type(v) in (int, float, str) for row in out["rows"] for v in row)


def test_interlock_shutter_closed(env):
    h, _ = env
    h.proto.shutter = "Closed"
    with pytest.raises(InterlockError) as e:
        go(ScanRunner(), env)
    assert "shutter" in e.value.reason
    assert h.wafer_stage.calls == []


def test_interlock_kv_low(env):
    h, _ = env
    h.proto.kv = 5.0
    with pytest.raises(InterlockError):
        go(ScanRunner(), env)
    assert h.wafer_stage.calls == []


def test_interlock_uncalibrated(env):
    h, _ = env
    h.mono._calibrated = False
    with pytest.raises(InterlockError):
        go(ScanRunner(), env)
    assert h.wafer_stage.calls == []


def test_interlock_radius(env):
    h, _ = env
    with pytest.raises(InterlockError) as e:
        go(ScanRunner(), env, x=60, y=60)
    assert "75" in e.value.reason
    assert h.wafer_stage.calls == []


def test_busy(env):
    h, _ = env
    h.mono.move_delay = 0.05
    r = ScanRunner()
    sid = go(r, env, n_points=20)
    with pytest.raises(BusyError):
        go(r, env)
    r.stop(sid)
    wait(r, sid)


def test_stop_mid_scan(env):
    h, _ = env
    h.mono.move_delay = 0.05
    r = ScanRunner()
    sid = go(r, env, n_points=40)
    t0 = time.time()
    while r.state(sid)["n_points"] < 3 and time.time() - t0 < 30:
        time.sleep(0.01)
    r.stop(sid)
    s = wait(r, sid)
    assert s["state"] == "stopped", s
    assert s["exd_path"] and Path(s["exd_path"]).is_file()
    assert 3 <= s["n_points"] < 40


def test_stop_during_move(env):
    h, _ = env
    h.wafer_stage.move_delay = 0.5
    r = ScanRunner()
    sid = go(r, env)
    r.stop(sid)
    s = wait(r, sid)
    assert s["state"] == "stopped", s
    assert s["exd_path"] is None
    assert h.mono.calls == [] and h.mono._n_calls == 0


def test_watchdog(env):
    h, _ = env
    h.mono.move_delay = 0.3  # keep the scan alive past the first row
    r = ScanRunner(watchdog_margin_s=0.5)
    sid = go(r, env, n_points=3)
    t0 = time.time()
    while r.state(sid)["n_points"] < 1 and time.time() - t0 < 30:
        time.sleep(0.005)
    h.ketek.hang = True
    try:
        s = wait(r, sid, timeout=30)
        assert s["state"] == "error", s
        assert s["error"].startswith("watchdog timeout")
        assert h.mono.stop_called
    finally:
        h.ketek.hang = False


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_scan_exception(env):
    h, _ = env
    h.mono.fail_on_call = 1
    r = ScanRunner()
    sid = go(r, env)
    s = wait(r, sid)
    assert s["state"] == "error", s
    assert "RuntimeError" in s["error"] and "fake mono failure" in s["error"]


def test_xchanger_station_moves_only_if_different(env):
    h, _ = env
    r = ScanRunner()
    h.xchanger.station = 3
    wait(r, go(r, env, station=3))
    assert h.xchanger.station == 3
    calls = []
    orig = h.xchanger.go_to_station
    h.xchanger.go_to_station = lambda n: (calls.append(n), orig(n))
    wait(r, go(r, env, station=3))
    assert calls == []
    wait(r, go(r, env, station=2))
    assert calls == [2] and h.xchanger.station == 2


def test_mcas_and_artifacts(env):
    r = ScanRunner()
    sid = go(r, env)
    wait(r, sid)
    assert np.load(BytesIO(r.mcas_bytes(sid)))["mcas"].shape == (4, 4096)
    assert r.artifacts(sid)["scan_def"]["zone_defs"]
    assert "metadata" in r.artifacts(sid)
    with pytest.raises(KeyError):
        r.state("nope")


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_watchdog_covers_start_hang_and_busy_until_released(env):
    h, _ = env
    h.ketek.hang = True  # hangs the header ping inside scan.start()
    r = ScanRunner(watchdog_margin_s=0.3)
    sid = go(r, env)
    try:
        s = wait(r, sid, timeout=10)
        assert s["state"] == "error" and s["error"].startswith("watchdog timeout"), s
        assert h.mono.stop_called
        with pytest.raises(BusyError):  # hung worker still alive
            go(r, env)
    finally:
        h.ketek.hang = False
    t0 = time.time()
    while True:
        try:
            sid2 = go(r, env)
            break
        except BusyError:
            assert time.time() - t0 < 15
            time.sleep(0.05)
    assert wait(r, sid2)["state"] == "done"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_stop_before_first_point_is_stopped(env):
    h, _ = env
    h.ketek.hang = True  # hold the scan before any row
    r = ScanRunner(watchdog_margin_s=30)
    sid = go(r, env)
    t0 = time.time()
    # wait until scan.start() has begun (stop event exists) so stop() reaches the vendor scan
    while getattr(r._scans[sid].scan, "_stop_event", None) is None and time.time() - t0 < 10:
        time.sleep(0.01)
    r.stop(sid)
    h.ketek.hang = False
    s = wait(r, sid)
    assert s["state"] == "stopped" and s["exd_path"] is None and s["error"] is None, s


def _saved_roi(path):
    import json
    import zipfile
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("scan_def.json"))["ROI"]


def test_roi_element_rewrites_roi(env):
    import easyxafs.scan
    r = ScanRunner()
    h, save_dir = env
    sid = r.start(scan_def(), 1.0, 2.0, None, SAVENAME, save_dir, roi_element="Fe")
    s = wait(r, sid)
    assert s["state"] == "done", s
    lo, hi = easyxafs.scan.get_automatic_fluorescence_ROI("Fe")
    roi = _saved_roi(s["exd_path"])
    assert (roi["roi_min"], roi["roi_max"]) == (lo, hi)
    assert (lo, hi) != (800, 1000)


def test_roi_unchanged_without_element(env):
    r = ScanRunner()
    s = wait(r, go(r, env))
    roi = _saved_roi(s["exd_path"])
    assert (roi["roi_min"], roi["roi_max"]) == (800, 1000)


def test_roi_unknown_element_interlock_before_motion(env):
    h, save_dir = env
    r = ScanRunner()
    with pytest.raises(InterlockError) as e:
        r.start(scan_def(), 1.0, 2.0, None, SAVENAME, save_dir, roi_element="Xx")
    assert "Xx" in e.value.reason
    assert h.wafer_stage.calls == []
