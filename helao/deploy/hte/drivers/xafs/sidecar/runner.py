"""Scan runner for the XAFS sidecar (Python 3.9, vendor easyxafs).

Runs one vendor scan at a time on a worker thread, enforces safety interlocks,
buffers per-point rows, supports stop, and has a watchdog. easyxafs singletons
are only reached through module attributes so the sim patches apply.
"""
import json
import math
import threading
import time
import traceback
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

ACTIVE = ("queued", "moving", "running", "saving")
MAX_RADIUS_MM = 75.0
MIN_KV = 10.0

# NormalScan lets exceptions escape its thread: record them per thread.
_thread_errors: Dict[threading.Thread, str] = {}
_prev_excepthook = threading.excepthook


def _record_excepthook(args: Any) -> None:
    if args.thread is not None:
        _thread_errors[args.thread] = "".join(
            traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
        )
    _prev_excepthook(args)


threading.excepthook = _record_excepthook


class InterlockError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BusyError(Exception):
    pass


class _Scan:
    def __init__(self) -> None:
        self.state = "queued"
        self.scan: Any = None
        self.rows: List[list] = []
        self.columns: List[str] = []
        self.n_expected = 0
        self.est_total = 0.0
        self.exd_path: Optional[str] = None
        self.error: Optional[str] = None
        self.stop_requested = False
        self.timed_out = False
        self.worker: Optional[threading.Thread] = None
        self.thread: Optional[threading.Thread] = None  # vendor scan thread
        self.t0 = time.monotonic()
        self.t_end: Optional[float] = None


class ScanRunner:
    def __init__(self, watchdog_margin_s: float = 120.0) -> None:
        self.watchdog_margin_s = watchdog_margin_s
        self._lock = threading.Lock()
        self._scans: Dict[str, _Scan] = {}

    # -- interlocks -------------------------------------------------------
    def check_interlocks(self, x_mm: float, y_mm: float) -> None:
        import easyxafs.scan
        import pyprotohv

        if not easyxafs.scan.mono._calibrated:
            raise InterlockError("monochromator not calibrated")
        proto = pyprotohv.proto_controller
        if proto.get_shutter_status() == "Closed":
            raise InterlockError("shutter closed")
        kv = proto.readback_kv_ma()[0]
        if kv < MIN_KV:
            raise InterlockError("x-ray kV %.1f below %.0f" % (kv, MIN_KV))
        if math.hypot(x_mm, y_mm) > MAX_RADIUS_MM:
            raise InterlockError("position outside %.0f mm radius" % MAX_RADIUS_MM)

    # -- control ----------------------------------------------------------
    def busy(self) -> bool:
        """A scan is active, or a watchdog-errored record still has live threads."""
        return any(s.state in ACTIVE
                   or (s.worker is not None and s.worker.is_alive())
                   or (s.thread is not None and s.thread.is_alive())
                   for s in self._scans.values())

    def start(self, scan_def: dict, x_mm: float, y_mm: float,
              xchanger_station: Optional[int], savename: str, save_dir: str,
              duration_scale: float = 1.0, roi_element: str = "") -> str:
        with self._lock:
            if self.busy():
                raise BusyError("a scan is already active")
            self.check_interlocks(x_mm, y_mm)
            roi = None
            if roi_element:  # resolve before any motion, as WaferGridScans does for Izero
                import easyxafs.scan
                try:
                    roi = easyxafs.scan.get_automatic_fluorescence_ROI(roi_element)
                except Exception as e:
                    raise InterlockError("cannot compute ROI for element %r: %s" % (roi_element, e))
            scan_id = uuid.uuid4().hex
            rec = _Scan()
            self._scans[scan_id] = rec
            rec.worker = threading.Thread(
                target=self._run, name="ScanRunner",
                args=(rec, scan_def, x_mm, y_mm, xchanger_station, savename, save_dir, duration_scale, roi),
                daemon=True,
            )
            rec.worker.start()
        return scan_id

    def stop(self, scan_id: str) -> None:
        rec = self._get(scan_id)
        rec.stop_requested = True
        scan = rec.scan
        if scan is not None and getattr(scan, "_stop_event", None) is not None:
            scan.stop()

    def _get(self, scan_id: str) -> _Scan:
        return self._scans[scan_id]  # KeyError if unknown

    # -- worker -----------------------------------------------------------
    def _run(self, rec: _Scan, scan_def: dict, x_mm: float, y_mm: float,
             station: Optional[int], savename: str, save_dir: str, scale: float,
             roi: Optional[tuple] = None) -> None:
        try:
            self._run_inner(rec, scan_def, x_mm, y_mm, station, savename, save_dir, scale, roi)
        except Exception:
            rec.error = traceback.format_exc()
            rec.state = "error"
        rec.scan = None  # drop MCA data; mcas_bytes/artifacts read exd_path
        rec.t_end = time.monotonic()

    def _run_inner(self, rec: _Scan, scan_def: dict, x_mm: float, y_mm: float,
                   station: Optional[int], savename: str, save_dir: str, scale: float,
                   roi: Optional[tuple] = None) -> None:
        import easyxafs
        import easyxafs.rowland
        import easyxafs.saveable_scan
        import easyxafs.scan
        import easyxafs.wafer_stage_motor_control
        import easyxafs.xchanger_control

        rec.state = "moving"
        xch = easyxafs.xchanger_control.xchanger
        if station is not None:  # unconditional: vendor go_to_deg skips moves within 0.01 deg
            xch.go_to_station(station)
            xch.wait_until_idle()
        stage = easyxafs.wafer_stage_motor_control.wafer_stage
        stage.go_to_wafer_xy(x_mm, y_mm)
        stage.wait_until_idle()
        if rec.stop_requested:
            rec.state = "stopped"
            return

        easyxafs.saveable_scan.SAVEDIR = Path(save_dir)
        easyxafs.rowland.alpha = np.deg2rad(scan_def.get("alpha", 0))
        scan = easyxafs.scan.load_scan_def(scan_def)
        if scale != 1:
            scan.scale_scan_times(scale)
        if roi is not None:  # same as WaferGridScans Izero: vendor only touches scan_def
            scan.scan_def['ROI']['roi_min'] = roi[0]
            scan.scan_def['ROI']['roi_max'] = roi[1]
        scan.savename = str(Path(save_dir) / savename)
        scan._saveaftercomplete = True
        try:
            rec.est_total = float(scan.estimate_scan_time())
        except Exception:
            rec.est_total = float(sum(z.get("duration", 0) for z in scan.scan_def["zone_defs"]))
        rec.scan = scan

        rec.state = "running"

        def cb(s: Any) -> None:
            row = [v.item() if hasattr(v, "item") else v
                   for v in list(s.data[-1][:-1]) + list(s.encoder_readings[-1])]
            with self._lock:
                if not rec.columns:
                    rec.columns = list(s.data_headers[:-1]) + list(s.encoder_header)
                    rec.n_expected = int(s.num_steps_total)
                rec.rows.append(row)

        timeout = rec.est_total * 2 + self.watchdog_margin_s
        deadline = time.monotonic() + timeout
        fire_lock = threading.Lock()

        def on_timeout() -> None:
            with fire_lock:
                if rec.timed_out:
                    return
                rec.timed_out = True
                rec.error = "watchdog timeout after %.0f s" % timeout
                rec.state = "error"
            easyxafs.scan.mono.stop()
            if getattr(scan, "_stop_event", None) is not None:
                scan.stop()

        timer = threading.Timer(timeout, on_timeout)  # also covers a hang inside scan.start()
        timer.daemon = True
        timer.start()
        try:
            scan.start(callback=cb)
            rec.thread = thread = scan._thread
            rec.columns = list(scan.data_headers[:-1]) + list(scan.encoder_header)
            rec.n_expected = int(scan.num_steps_total)
            if rec.stop_requested:
                scan.stop()
            thread.join(max(0.0, deadline - time.monotonic()))
            if thread.is_alive():
                on_timeout()
        finally:
            timer.cancel()
        if rec.timed_out:
            return

        exc = _thread_errors.pop(thread, None)
        n = len(rec.rows)
        if rec.stop_requested and n == 0:
            rec.state = "stopped"  # nothing to save; vendor empty-data save error is expected
        elif exc:
            rec.error, rec.state = exc, "error"
        elif rec.stop_requested:
            rec.exd_path = scan.saved_path
            rec.state = "stopped"
        elif n < rec.n_expected:
            rec.error, rec.state = "scan ended early (%d/%d points)" % (n, rec.n_expected), "error"
        elif scan.saved_path is None:
            rec.error, rec.state = "save failed", "error"
        else:
            rec.exd_path = scan.saved_path
            rec.state = "done"

    # -- queries ----------------------------------------------------------
    def state(self, scan_id: str) -> dict:
        rec = self._get(scan_id)
        st = rec.state
        # NormalScan sets _finished before its saves, so it marks "saving".
        if st == "running" and getattr(rec.scan, "_finished", False):
            st = "saving"
        end = rec.t_end if rec.t_end is not None else time.monotonic()
        return {
            "state": st, "n_points": len(rec.rows), "n_expected": rec.n_expected,
            "elapsed": end - rec.t0, "est_total": rec.est_total,
            "exd_path": rec.exd_path, "error": rec.error,
        }

    def rows(self, scan_id: str, since: int) -> dict:
        rec = self._get(scan_id)
        with self._lock:
            return {"columns": list(rec.columns), "rows": [list(r) for r in rec.rows[since:]]}

    def _zip(self, scan_id: str) -> zipfile.ZipFile:
        rec = self._get(scan_id)
        if rec.state not in ("done", "stopped") or not rec.exd_path:
            raise RuntimeError("no exd for scan in state %r" % rec.state)
        return zipfile.ZipFile(rec.exd_path)

    def mcas_bytes(self, scan_id: str) -> bytes:
        with self._zip(scan_id) as z:
            name = next(n for n in z.namelist() if n.endswith("_mcas.npz"))
            return z.read(name)

    def artifacts(self, scan_id: str) -> dict:
        with self._zip(scan_id) as z:
            return {
                "scan_def": json.loads(z.read("scan_def.json")),
                "metadata": json.loads(z.read("metadata.json")),
            }
