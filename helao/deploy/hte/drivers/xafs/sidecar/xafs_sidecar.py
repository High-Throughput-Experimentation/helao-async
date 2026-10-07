"""XAFS sidecar HTTP app (Python 3.9, vendor easyxafs). Imports nothing from helao."""
import argparse
import logging
import os
import sys
import tempfile
import threading
import time
import traceback
import uuid
from typing import Any, Callable, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

try:  # package import (tests) or script import (CLI run from this directory)
    from . import hardware
    from .runner import BusyError, InterlockError, ScanRunner
except ImportError:
    import hardware  # type: ignore
    from runner import BusyError, InterlockError, ScanRunner  # type: ignore

ACTIVE = ("queued", "moving", "running", "saving")


class InitFlags(BaseModel):
    mono: bool = True
    ketek: bool = True
    wafer_stage: bool = True
    xchanger: bool = True
    proto: bool = True


class CalibrateReq(BaseModel):
    devices: List[Literal["mono", "wafer_linear", "wafer_rotary", "xchanger"]]


class ScanReq(BaseModel):
    scan_def: Dict[str, Any]
    x_mm: float
    y_mm: float
    xchanger_station: Optional[int] = None
    savename: str
    save_dir: str
    duration_scale: float = 1.0
    roi_element: str = ""


class XrayReq(BaseModel):
    kv: Optional[float] = None
    ma: Optional[float] = None
    shutter: Optional[Literal["open", "close"]] = None
    off: bool = False


def create_app(simulate: bool, lock_path: str, state_dir: str,
               exit_fn: Optional[Callable[[], None]] = None) -> FastAPI:
    """exit_fn runs shortly after /shutdown replies; None means do not exit (tests)."""
    hardware._inited.clear()
    app = FastAPI()
    app.state.sim = None
    if simulate:  # must run before easyxafs is used; easyxafs import resets root logging
        try:
            from . import sim_hw
        except ImportError:
            import sim_hw  # type: ignore
        app.state.sim = sim_hw.install_sim(state_dir)
    import easyxafs  # noqa: F401  its logging_setup clears root handlers: import before ours
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(getattr(h, "_xafs_sidecar", False) for h in root.handlers):
        h = logging.StreamHandler()
        h._xafs_sidecar = True  # type: ignore[attr-defined]
        h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        root.addHandler(h)
    runner = ScanRunner()
    jobs = {}  # type: Dict[str, dict]
    st = {"hw_initialized": False, "scan_id": None}

    def scan_active() -> bool:
        sid = st["scan_id"]
        return bool(sid) and runner.state(sid)["state"] in ACTIVE

    def calibrating() -> bool:
        return any(j["state"] == "running" for j in jobs.values())

    def need_lock() -> None:
        if not hardware.owns_lock(lock_path):
            raise HTTPException(423, "hardware lock not held by this process; POST /initialize first")

    @app.exception_handler(InterlockError)
    async def _interlock(request: Request, exc: InterlockError) -> JSONResponse:
        return JSONResponse({"detail": exc.reason}, status_code=409)

    @app.exception_handler(BusyError)
    async def _busy(request: Request, exc: BusyError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(KeyError)
    async def _key(request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse({"detail": "unknown id %s" % exc}, status_code=404)

    @app.exception_handler(hardware.LockHeldError)
    async def _lock(request: Request, exc: hardware.LockHeldError) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "pid": exc.pid}, status_code=423)

    @app.get("/health")
    def health() -> dict:
        try:
            from pkg_resources import get_distribution
            ver = get_distribution("easyxafs_python").version
        except Exception:
            ver = "unknown"
        return {"easyxafs_version": ver, "python": sys.version.split()[0],
                "pid": os.getpid(), "hw_initialized": st["hw_initialized"],
                "simulate": simulate}

    @app.post("/initialize")
    def initialize(flags: InitFlags) -> dict:
        hardware.acquire_lock(lock_path)
        out = hardware.initialize(flags.dict())
        st["hw_initialized"] = all(v == "ok" for v in out.values())
        return out

    @app.get("/status")
    def status() -> dict:
        out = hardware.status()
        sid = st["scan_id"]
        out["scan_id"] = sid if scan_active() else None
        return out

    @app.post("/calibrate")
    def calibrate(req: CalibrateReq) -> dict:
        need_lock()
        if scan_active() or calibrating():
            raise HTTPException(409, "scan or calibration in progress")
        jid = uuid.uuid4().hex
        job = {"state": "running", "error": None}
        jobs[jid] = job

        def work() -> None:
            try:
                hardware.calibrate(req.devices)
                job["state"] = "done"
            except Exception:
                job["error"] = traceback.format_exc()
                job["state"] = "error"

        threading.Thread(target=work, name="calibrate", daemon=True).start()
        return {"job_id": jid}

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        return jobs[job_id]

    @app.post("/scans")
    def start_scan(req: ScanReq) -> dict:
        need_lock()
        if calibrating():
            raise HTTPException(409, "calibration in progress")
        sid = runner.start(req.scan_def, req.x_mm, req.y_mm, req.xchanger_station,
                           req.savename, req.save_dir, req.duration_scale, req.roi_element)
        st["scan_id"] = sid
        return {"scan_id": sid}

    @app.get("/scans/{scan_id}")
    def scan_state(scan_id: str) -> dict:
        return runner.state(scan_id)

    @app.get("/scans/{scan_id}/rows")
    def scan_rows(scan_id: str, since: int = 0) -> dict:
        return runner.rows(scan_id, since)

    @app.get("/scans/{scan_id}/mcas")
    def scan_mcas(scan_id: str) -> Response:
        try:
            data = runner.mcas_bytes(scan_id)
        except RuntimeError as e:
            return JSONResponse({"detail": str(e)}, status_code=409)
        return Response(content=data, media_type="application/octet-stream")

    @app.get("/scans/{scan_id}/artifacts")
    def scan_artifacts(scan_id: str) -> Any:
        try:
            return runner.artifacts(scan_id)
        except RuntimeError as e:
            return JSONResponse({"detail": str(e)}, status_code=409)

    @app.post("/scans/{scan_id}/stop")
    def scan_stop(scan_id: str) -> dict:
        runner.stop(scan_id)
        return {"ok": True}

    @app.post("/xray")
    def xray(req: XrayReq) -> dict:
        need_lock()
        return hardware.xray(req.kv, req.ma, req.shutter, req.off)

    @app.post("/shutdown")
    def shutdown() -> dict:
        held = hardware.owns_lock(lock_path)
        sid = st["scan_id"]
        if sid and scan_active():
            runner.stop(sid)
            deadline = time.monotonic() + 30  # let the scan finish saving before we exit
            while scan_active() and time.monotonic() < deadline:
                time.sleep(0.05)
        if held:
            try:
                hardware.xray(shutter="close")
            except Exception:
                logging.exception("shutter close failed during shutdown")
        hardware.release_lock(lock_path)
        if exit_fn is not None:
            threading.Timer(0.2, exit_fn).start()
        return {"ok": True}

    return app


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--lock-file",
                    default=os.path.join(os.environ.get("TEMP", tempfile.gettempdir()),
                                         "easyxafs_sidecar.lock"))
    ap.add_argument("--state-dir", default=os.path.join(tempfile.gettempdir(), "easyxafs_sidecar"))
    a = ap.parse_args(argv)
    import uvicorn
    app = create_app(a.simulate, a.lock_file, a.state_dir, exit_fn=lambda: os._exit(0))
    uvicorn.run(app, host="127.0.0.1", port=a.port)


if __name__ == "__main__":
    main()
