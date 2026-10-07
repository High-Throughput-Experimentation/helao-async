"""HelaoDriver client for the easyXAFS sidecar (HTTP on loopback, sync httpx).

The sidecar owns the hardware in a separate Python process; this driver only
speaks HTTP and can optionally spawn that process. Public methods block, never
raise, and return a `DriverResponse` (payload in `.data`). The action server
calls them through `asyncio.to_thread`.
"""

import subprocess
import time
from typing import Optional

import httpx

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)

_BUSY = {"queued", "moving", "running", "saving"}
_OK = {"done", "stopped"}


def _ok(message: str, data=None, status=DriverStatus.ok) -> DriverResponse:
    return DriverResponse(
        response=DriverResponseType.success, message=message, data=data, status=status
    )


def _fail(message: str, data=None) -> DriverResponse:
    return DriverResponse(
        response=DriverResponseType.failed,
        message=message,
        data=data,
        status=DriverStatus.error,
    )


class XafsSidecarDriver(HelaoDriver):
    """Client for the easyXAFS sidecar HTTP API.

    Config keys: `sidecar_port` (required), `sidecar_host` ("127.0.0.1"),
    `spawn_sidecar` (False), `sidecar_python`, `sidecar_script`, `sidecar_args`
    ([]), `request_timeout` (10.0 s), `spawn_wait_s` (30.0 s). `__init__` does no
    I/O. `current_scan_id` is set by `start_scan`.
    """

    def __init__(self, config: dict = {}):
        super().__init__(config=config)
        c = self.config
        self.port = c.get("sidecar_port")
        self.spawn = c.get("spawn_sidecar", False)
        self.timeout = c.get("request_timeout", 10.0)
        self.spawn_wait_s = c.get("spawn_wait_s", 30.0)
        self.base_url = f"http://{c.get('sidecar_host', '127.0.0.1')}:{self.port}"
        self.client = httpx.Client(base_url=self.base_url, timeout=self.timeout)
        self.current_scan_id: Optional[str] = None
        self._proc: Optional[subprocess.Popen] = None
        self._init_flags: Optional[dict] = None

    def _call(self, method: str, path: str, desc: str, **kw) -> DriverResponse:
        """One HTTP request. Success -> data is parsed JSON (or bytes if
        `raw=True`); HTTP error -> data has http_status/detail; transport error
        -> failed with no data."""
        raw = kw.pop("raw", False)
        try:
            resp = self.client.request(method, path, **kw)
        except Exception as exc:
            return _fail(f"{desc}: {type(exc).__name__}: {exc}")
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            return _fail(
                f"{desc}: HTTP {resp.status_code} {detail}",
                {"http_status": resp.status_code, "detail": detail},
            )
        try:
            data = resp.content if raw else resp.json()
        except Exception as exc:
            return _fail(f"{desc}: bad response body: {exc}")
        return _ok(desc, data)

    @staticmethod
    def _is_sidecar(data) -> bool:
        return isinstance(data, dict) and all(
            k in data for k in ("pid", "hw_initialized", "simulate")
        )

    def _probe(self) -> DriverResponse:
        """GET /health; success only if the body identifies as the sidecar."""
        r = self._call("GET", "/health", "sidecar health")
        if r.response == DriverResponseType.success and not self._is_sidecar(r.data):
            return _fail("port answered /health but is not the xafs sidecar", r.data)
        return r

    def _check_simulate(self, r: DriverResponse, what: str) -> DriverResponse:
        want = bool(self.config.get("simulate", False))
        if bool(r.data["simulate"]) != want:
            return _fail(
                f"{what} sidecar simulate={r.data['simulate']} but config simulate={want}"
            )
        return _ok(what, r.data)

    def connect(self) -> DriverResponse:
        """Probe `/health`; if down and `spawn_sidecar`, spawn and poll it."""
        if self.port is None:
            return _fail("missing sidecar_port in config")
        if self.client.is_closed:  # reconnect after disconnect()
            self.client = httpx.Client(base_url=self.base_url, timeout=self.timeout)
        r = self._probe()
        if r.response == DriverResponseType.success:
            return self._check_simulate(r, "connected to existing sidecar")
        if not self.spawn:
            return _fail(f"sidecar unreachable and spawn_sidecar is off: {r.message}")
        self._terminate(graceful=False)  # unhealthy leftover from a prior connect
        c = self.config
        args = list(c.get("sidecar_args", []))
        if c.get("simulate", False) and "--simulate" not in args:
            args.append("--simulate")
        try:
            self._proc = subprocess.Popen(
                [c["sidecar_python"], c["sidecar_script"], "--port", str(self.port), *args]
            )
        except Exception as exc:
            return _fail(f"could not spawn sidecar: {type(exc).__name__}: {exc}")
        deadline = time.monotonic() + self.spawn_wait_s
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                return _fail(f"sidecar exited with code {self._proc.returncode}")
            r = self._probe()
            if r.response == DriverResponseType.success:
                r = self._check_simulate(r, "spawned sidecar")
                if r.response != DriverResponseType.success:
                    self._terminate(graceful=False)
                return r
            time.sleep(0.25)
        self._terminate(graceful=False)
        return _fail(f"sidecar did not answer /health within {self.spawn_wait_s} s")

    def get_status(self) -> DriverResponse:
        """No current scan: ok if sidecar reachable. Else map the scan state."""
        if self.current_scan_id is None:
            r = self._probe()
            if r.response == DriverResponseType.success:
                return _ok("sidecar reachable", {"state": None})
            return r
        r = self.scan_state(self.current_scan_id)
        if r.response != DriverResponseType.success:
            return r
        state = r.data.get("state")
        status = (
            DriverStatus.busy
            if state in _BUSY
            else DriverStatus.ok if state in _OK else DriverStatus.error
        )
        return _ok(f"scan {state}", {"state": state, **r.data}, status)

    def stop(self) -> DriverResponse:
        """Stop the current scan (no-op success if none)."""
        if self.current_scan_id is None:
            return _ok("no current scan")
        return self._call("POST", f"/scans/{self.current_scan_id}/stop", "stop scan")

    def reset(self) -> DriverResponse:
        """Re-run `/initialize` with the flags of the last `initialize` call."""
        if self._init_flags is None:
            return _fail("reset before initialize: no device flags known")
        return self.initialize(self._init_flags)

    def disconnect(self) -> DriverResponse:
        """Close the client; if this driver spawned the sidecar, shut it down."""
        if self._proc is not None:
            # sidecar waits up to 30 s for an active scan to finish saving
            self._call("POST", "/shutdown", "shutdown sidecar", timeout=35.0)
            self._terminate(graceful=True)
        self.client.close()
        return _ok("disconnected")

    def _terminate(self, graceful: bool = False, wait: float = 10.0):
        """Stop the spawned process. `graceful` waits `wait` s for exit first
        (after /shutdown); otherwise terminate immediately, then kill."""
        p, self._proc = self._proc, None
        if p is None or p.poll() is not None:
            return
        if graceful:
            try:
                p.wait(timeout=wait)
                return
            except subprocess.TimeoutExpired:
                pass
        p.terminate()
        try:
            p.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()

    def initialize(self, flags: dict) -> DriverResponse:
        """POST /initialize; data is the per-device ok/error map."""
        self._init_flags = dict(flags)
        return self._call("POST", "/initialize", "initialize", json=flags)

    def start_scan(self, **body) -> DriverResponse:
        """POST /scans; sets `current_scan_id`; data={"scan_id": ...}."""
        r = self._call("POST", "/scans", "start scan", json=body)
        if r.response == DriverResponseType.success:
            self.current_scan_id = r.data["scan_id"]
        return r

    def scan_state(self, scan_id: str) -> DriverResponse:
        return self._call("GET", f"/scans/{scan_id}", "scan state")

    def rows_since(self, scan_id: str, since: int) -> DriverResponse:
        return self._call(
            "GET", f"/scans/{scan_id}/rows", "scan rows", params={"since": since}
        )

    def fetch_mcas(self, scan_id: str) -> DriverResponse:
        r = self._call("GET", f"/scans/{scan_id}/mcas", "scan mcas", raw=True)
        if r.response == DriverResponseType.success:
            r.data = {"npz": r.data}
        return r

    def fetch_artifacts(self, scan_id: str) -> DriverResponse:
        return self._call("GET", f"/scans/{scan_id}/artifacts", "scan artifacts")

    def xray(self, **body) -> DriverResponse:
        return self._call("POST", "/xray", "xray", json=body)

    def calibrate(self, devices: list) -> DriverResponse:
        """POST /calibrate; data={"job_id": ...}."""
        return self._call("POST", "/calibrate", "calibrate", json={"devices": devices})

    def job_state(self, job_id: str) -> DriverResponse:
        """GET /jobs/{id}; data={"state": running|done|error, "error": ...}."""
        return self._call("GET", f"/jobs/{job_id}", "job state")

    def hw_status(self) -> DriverResponse:
        """GET /status; hardware positions, shutter/kV/mA, mono calibration."""
        return self._call("GET", "/status", "hardware status")
