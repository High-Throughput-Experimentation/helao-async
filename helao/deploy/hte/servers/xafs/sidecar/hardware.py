"""Hardware facade and process lock for the XAFS sidecar (Python 3.9).

easyxafs / pyprotohv singletons are only reached through module attributes so
the sim patches apply.
"""

import os
from typing import Any, Dict, List, Optional

import psutil

DEVICES = ("mono", "ketek", "wafer_stage", "xchanger", "proto")

_inited = set()  # real mode: devices we already initialized


class LockHeldError(Exception):
    def __init__(self, pid: int) -> None:
        super().__init__("hardware lock held by pid %d" % pid)
        self.pid = pid


def acquire_lock(lock_path: str) -> None:
    try:
        with open(lock_path, encoding="utf-8") as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        pid = None
    if pid is not None and pid != os.getpid() and psutil.pid_exists(pid):
        raise LockHeldError(pid)
    with open(lock_path, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))


def owns_lock(lock_path: str) -> bool:
    try:
        with open(lock_path, encoding="utf-8") as f:
            return int(f.read().strip()) == os.getpid()
    except (OSError, ValueError):
        return False


def release_lock(lock_path: str) -> None:
    """Delete the lock only if it holds our PID."""
    if owns_lock(lock_path):
        try:
            os.remove(lock_path)
        except FileNotFoundError:
            pass


def _init_device(name: str) -> None:
    import easyxafs.ketek
    import easyxafs.monochromator
    import easyxafs.wafer_stage_motor_control
    import easyxafs.xchanger_control

    if name == "mono":
        easyxafs.monochromator.mono.initialize()
        easyxafs.monochromator.mono.check_calibration()
    elif name == "ketek":
        easyxafs.ketek.initialize()
    elif name == "wafer_stage":
        if easyxafs.wafer_stage_motor_control.wafer_stage is None:
            easyxafs.wafer_stage_motor_control.initialize_wafer_stage()
    elif name == "xchanger":
        if easyxafs.xchanger_control.xchanger is None:
            easyxafs.xchanger_control.initialize()
    elif name == "proto":
        import pyprotohv
        from pyprotohv import proto_controller  # noqa: F401  (notebook setup)

        if pyprotohv.proto_controller is None:
            raise RuntimeError("pyprotohv.proto_controller is None")


def initialize(flags: dict) -> dict:
    out = {}  # type: Dict[str, str]
    for name in DEVICES:
        if not flags.get(name, True):
            continue
        if name in _inited:
            out[name] = "ok"
            continue
        try:
            _init_device(name)
            _inited.add(name)
            out[name] = "ok"
        except Exception as e:
            out[name] = "%s: %s" % (type(e).__name__, e)
    return out


def _proto() -> Any:
    import pyprotohv

    return pyprotohv.proto_controller


def status() -> dict:
    import easyxafs.monochromator
    import easyxafs.wafer_stage_motor_control
    import easyxafs.xchanger_control

    mono = easyxafs.monochromator.mono
    stage = easyxafs.wafer_stage_motor_control.wafer_stage
    xch = easyxafs.xchanger_control.xchanger
    proto = _proto()
    kv_ma = proto.readback_kv_ma() if proto is not None else None
    return {
        "mono_calibrated": bool(mono._calibrated),
        "mono_positions": {k: int(v) for k, v in mono.get_positions().items()},
        "mono_bragg": {
            k: float(v) for k, v in mono.get_current_positions_bragg().items()
        },
        "wafer_xy": (
            list(stage.get_current_position_wafer_xy()) if stage is not None else None
        ),
        "xchanger_station": xch.get_current_station() if xch is not None else None,
        "proto": (
            None
            if proto is None
            else {
                "kv": kv_ma[0],
                "ma": kv_ma[1],
                "shutter": proto.get_shutter_status(),
            }
        ),
    }


def xray(
    kv: Optional[float] = None,
    ma: Optional[float] = None,
    shutter: Optional[str] = None,
    off: bool = False,
) -> dict:
    proto = _proto()
    if proto is None:
        raise RuntimeError("proto not initialized")
    if off:
        proto.xray_off()
        proto.wait_until_idle()
    elif kv is not None or ma is not None:
        cur = proto.readback_kv_ma()
        proto.set_kV_mA(cur[0] if kv is None else kv, cur[1] if ma is None else ma)
        proto.wait_until_idle()
    if shutter == "open":
        proto.open_shutter(block_until_complete=True)
    elif shutter == "close":
        proto.close_shutter(block_until_complete=True)
    kv_ma = proto.readback_kv_ma()
    return {"kv": kv_ma[0], "ma": kv_ma[1], "shutter": proto.get_shutter_status()}


def calibrate(devices: List[str]) -> None:
    import easyxafs.monochromator
    import easyxafs.wafer_stage_motor_control
    import easyxafs.xchanger_control

    for d in devices:
        if d == "mono":
            easyxafs.monochromator.mono.calibrate_all()
        elif d == "wafer_linear":
            easyxafs.wafer_stage_motor_control.wafer_stage.calibrate_linear_motor()
        elif d == "wafer_rotary":
            easyxafs.wafer_stage_motor_control.wafer_stage.calibrate_rotary_motor()
        elif d == "xchanger":
            easyxafs.xchanger_control.xchanger.calibrate()
        else:
            raise ValueError("unknown device %r" % d)
