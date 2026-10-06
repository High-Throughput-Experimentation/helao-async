"""XafsSidecarDriver against a local stub of the sidecar HTTP API."""

import http.server
import json
import pathlib
import socket
import subprocess
import sys
import threading

import pytest

from helao.core.drivers.helao_driver import DriverResponseType, DriverStatus
from helao.deploy.hte.drivers.xafs.driver import XafsSidecarDriver

HEALTH = {"pid": 1, "hw_initialized": False, "simulate": False}
FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class Stub:
    """Routes ``"METHOD /path"`` -> ``(status, json-or-bytes)``; logs requests."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _do(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n)) if n else None
                path = self.path.split("?")[0]
                stub.requests.append((self.command, self.path, body))
                status, payload = stub.routes.get(
                    f"{self.command} {path}", (404, {"detail": "nope"})
                )
                raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = _do

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def driver(self, **cfg):
        return XafsSidecarDriver(config={"sidecar_port": self.port, **cfg})


@pytest.fixture
def make_stub():
    stubs = []

    def _make(routes=None):
        stubs.append(Stub({"GET /health": (200, HEALTH), **(routes or {})}))
        return stubs[-1]

    yield _make
    for s in stubs:
        s.server.shutdown()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_connect_existing_sidecar(make_stub):
    resp = make_stub().driver().connect()
    assert resp.response == DriverResponseType.success
    assert resp.status == DriverStatus.ok


def test_connect_unreachable_no_spawn_fails():
    resp = XafsSidecarDriver(config={"sidecar_port": free_port()}).connect()
    assert resp.response == DriverResponseType.failed
    assert resp.status == DriverStatus.error


def test_connect_spawns_and_waits():
    d = XafsSidecarDriver(
        config={
            "sidecar_port": free_port(),
            "spawn_sidecar": True,
            "sidecar_python": sys.executable,
            "sidecar_script": str(FIXTURES / "slow_health_server.py"),
            "spawn_wait_s": 15.0,
        }
    )
    try:
        assert d.connect().response == DriverResponseType.success
        proc = d._proc
        assert proc is not None and proc.poll() is None
    finally:
        assert d.disconnect().response == DriverResponseType.success
    assert proc.poll() is not None


def test_status_mapping(make_stub):
    stub = make_stub({"GET /scans/s1": (200, {"state": "running"})})
    d = stub.driver()
    assert d.get_status().status == DriverStatus.ok  # no scan yet
    d.current_scan_id = "s1"
    r = d.get_status()
    assert r.status == DriverStatus.busy and r.data["state"] == "running"
    for state, want in [("done", DriverStatus.ok), ("error", DriverStatus.error)]:
        stub.routes["GET /scans/s1"] = (200, {"state": state})
        assert d.get_status().status == want
    stub.server.shutdown()
    stub.server.server_close()  # refuse connections instead of timing out
    assert d.get_status().status == DriverStatus.error


def test_start_scan_409(make_stub):
    stub = make_stub({"POST /scans": (409, {"detail": "interlock"})})
    d = stub.driver()
    r = d.start_scan(scan_def={})
    assert r.response == DriverResponseType.failed and r.status == DriverStatus.error
    assert r.data == {"http_status": 409, "detail": "interlock"}
    assert d.current_scan_id is None


def test_start_scan_ok_sets_current(make_stub):
    stub = make_stub({"POST /scans": (200, {"scan_id": "abc"})})
    d = stub.driver()
    r = d.start_scan(scan_def={"a": 1}, x_mm=1.0)
    assert r.data == {"scan_id": "abc"} and d.current_scan_id == "abc"
    assert stub.requests[-1][2] == {"scan_def": {"a": 1}, "x_mm": 1.0}


def test_stop_calls_current(make_stub):
    stub = make_stub({"POST /scans/s1/stop": (200, {})})
    d = stub.driver()
    d.current_scan_id = "s1"
    assert d.stop().response == DriverResponseType.success
    assert ("POST", "/scans/s1/stop", None) in stub.requests


def test_fetch_mcas_bytes(make_stub):
    stub = make_stub({"GET /scans/s1/mcas": (200, b"\x93NUMPY\x00")})
    r = stub.driver().fetch_mcas("s1")
    assert r.response == DriverResponseType.success
    assert r.data == {"npz": b"\x93NUMPY\x00"}


def test_rows_and_artifacts_and_reset(make_stub):
    stub = make_stub(
        {
            "GET /scans/s1/rows": (200, {"columns": ["a"], "rows": [[1]]}),
            "GET /scans/s1/artifacts": (200, {"scan_def": {}, "metadata": {}}),
            "POST /initialize": (200, {"mono": "ok"}),
        }
    )
    d = stub.driver()
    assert d.rows_since("s1", 3).data["rows"] == [[1]]
    assert ("GET", "/scans/s1/rows?since=3", None) in stub.requests
    assert d.fetch_artifacts("s1").data == {"scan_def": {}, "metadata": {}}
    assert d.reset().response == DriverResponseType.failed  # never initialized
    assert d.initialize({"mono": True}).data == {"mono": "ok"}
    assert d.reset().response == DriverResponseType.success
    assert stub.requests[-1][2] == {"mono": True}


def _spawn_driver(**extra):
    return XafsSidecarDriver(
        config={
            "sidecar_port": free_port(),
            "spawn_sidecar": True,
            "sidecar_python": sys.executable,
            "sidecar_script": str(FIXTURES / "slow_health_server.py"),
            "spawn_wait_s": 15.0,
            **extra,
        }
    )


def test_spawn_simulate_passes_flag_and_matches():
    d = _spawn_driver(simulate=True)
    try:
        assert d.connect().response == DriverResponseType.success
        assert "--simulate" in d._proc.args
    finally:
        d.disconnect()


def test_simulate_mismatch_existing_fails(make_stub):
    r = make_stub().driver(simulate=True).connect()  # stub reports simulate False
    assert r.response == DriverResponseType.failed


def test_simulate_mismatch_spawned_fails_and_kills():
    d = _spawn_driver(sidecar_args=[], simulate=False)
    d.config["sidecar_args"] = ["--simulate"]  # sidecar sims, config says real
    r = d.connect()
    assert r.response == DriverResponseType.failed and d._proc is None


def test_reconnect_after_disconnect(make_stub):
    d = make_stub().driver()
    assert d.connect().response == DriverResponseType.success
    d.disconnect()
    assert d.connect().response == DriverResponseType.success


def test_non_sidecar_health_rejected(make_stub):
    stub = make_stub({"GET /health": (200, {"ok": True})})
    assert stub.driver().connect().response == DriverResponseType.failed


def test_non_sidecar_health_spawns_instead(make_stub):
    stub = make_stub({"GET /health": (200, {"ok": True})})
    d = stub.driver(
        spawn_sidecar=True,
        sidecar_python=sys.executable,
        sidecar_script=str(FIXTURES / "slow_health_server.py"),
        spawn_wait_s=3.0,
    )
    try:
        d.connect()
        assert d._proc is not None  # a spawn was attempted
    finally:
        d.disconnect()


def test_second_connect_terminates_unhealthy_old_process():
    d = _spawn_driver(spawn_wait_s=0.3)  # fixture sleeps 1 s: times out
    assert d.connect().response == DriverResponseType.failed
    assert d._proc is None  # timeout path terminated it
    d.config["spawn_wait_s"], d.spawn_wait_s = 15.0, 15.0
    first = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    d._proc = first
    try:
        assert d.connect().response == DriverResponseType.success
        assert first.poll() is not None
    finally:
        d.disconnect()
        first.kill()
