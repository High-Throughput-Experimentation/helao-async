"""In-process hardware fakes so the vendor easyxafs scan loop runs without hardware.

Python 3.9 only (the easyxafs sim env). ``install_sim(state_dir)`` stubs the
vendor hardware modules in ``sys.modules``, imports easyxafs, and swaps the
real hardware singletons for the fakes below.
"""
import os
import sys
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

N_BINS = 4096
STAT_KEYS = ("realtime", "livetime", "triggers", "events", "icr", "ocr", "deadtime")


class FakeMono:
    def __init__(self) -> None:
        self.beta_offset = 0
        self.theta_offset = 0
        self.analyzer_radius = 500
        self._calibrated = True
        self._speed_setting = "high_speed"
        self.stored_encoders: Dict[str, int] = {
            "Beta": 0, "Detector": 0, "Rho": 0, "Theta": 0,
        }
        self.crystal2d = "Si(5,5,3)"  # extra: lets FakeKetek convert angle -> energy
        self.move_delay = 0.0
        self.fail_on_call: Optional[int] = None
        self.calls: List[float] = []
        self._n_calls = 0
        self.stop_called = False

    def move_to_bragg_angle(self, bragg: float) -> None:
        self._n_calls += 1
        if self.fail_on_call is not None and self._n_calls == self.fail_on_call:
            raise RuntimeError("fake mono failure")
        if self.move_delay:
            time.sleep(self.move_delay)
        self.calls.append(float(bragg))

    def wait_until_idle(self, *args: Any, **kwargs: Any) -> None:
        pass

    def get_encoder_readings(self) -> Dict[str, int]:
        return dict(self.stored_encoders)

    def get_positions(self) -> Dict[str, int]:
        return dict(self.stored_encoders)

    def stop(self) -> None:
        self.stop_called = True

    def check_calibration(self) -> bool:
        return self._calibrated

    def initialize(self) -> None:
        pass


class FakeKetek:
    def __init__(self, mono: FakeMono) -> None:
        self.mono = mono
        self.is_initialized = True
        self.SDD_cr_settings = "High"
        self.e0 = 9659.0  # extra: edge energy of the synthetic spectrum (Zn K)
        self.hang = False
        self._duration = 0.1

    def initialize(self) -> None:
        self.is_initialized = True

    def start_acquisition(self, duration: Optional[float] = None, channel: int = 0) -> None:
        self._duration = 0.1 if duration is None else float(duration)

    def wait_until_acquisition_complete(self) -> None:
        while self.hang:
            time.sleep(0.01)

    def _energy(self) -> float:
        import easyxafs_xray_utils

        if not self.mono.calls:
            return self.e0
        return float(easyxafs_xray_utils.bragg_energy(self.mono.calls[-1], self.mono.crystal2d))

    def get_spectrum(self, channel: int = 0) -> np.ndarray:
        e = self._energy()
        height = 1000 * (1 + np.arctan((e - self.e0) / 2) / np.pi + 0.5)
        x = np.arange(N_BINS)
        return np.rint(height * np.exp(-0.5 * ((x - 900) / 30.0) ** 2)).astype(np.int64)

    def get_statistics(self, channel: int = 0) -> Dict[str, float]:
        icr, ocr = 1000.0, 950.0
        d = self._duration
        vals = (d, 0.95 * d, icr * d, ocr * d, icr, ocr, 0.05)
        return dict(zip(STAT_KEYS, vals))


class _FakeMotor:
    def get_pos_mm(self) -> float:
        return 0.0

    def get_pos_deg(self) -> float:
        return 0.0


class FakeWaferStage:
    def __init__(self) -> None:
        self.move_delay = 0.0
        self.calls: List[Tuple[float, float]] = []
        self.pos: Tuple[float, float] = (0.0, 0.0)
        self.linear_motor = _FakeMotor()  # extra: saveable_scan metadata reads these
        self.rotary_motor = _FakeMotor()

    def go_to_wafer_xy(self, x: float, y: float) -> None:
        if self.move_delay:
            time.sleep(self.move_delay)
        self.calls.append((x, y))
        self.pos = (x, y)

    def wait_until_idle(self, timeout: float = 60) -> None:
        pass

    def get_current_position_wafer_xy(self) -> Tuple[float, float]:
        return self.pos

    def stop_motors(self) -> None:
        pass


class FakeXchanger:
    def __init__(self) -> None:
        self.station = 1

    def go_to_station(self, n: int) -> None:
        self.station = n

    def get_current_station(self) -> int:
        return self.station

    def get_pos_deg(self) -> float:
        return float(self.station)

    def wait_until_idle(self) -> None:
        pass


class FakeProto:
    def __init__(self) -> None:
        self.shutter = "Open"
        self.kv = 50.0
        self.ma = 1.0

    def get_shutter_status(self) -> str:
        return self.shutter

    def readback_kv_ma(self) -> Tuple[float, float]:
        return (self.kv, self.ma)

    def wait_until_idle(self) -> None:
        pass

    def set_kV_mA(self, kv: float, ma: float) -> None:
        self.kv, self.ma = kv, ma

    def open_shutter(self, block_until_complete: bool = True) -> None:
        self.shutter = "Open"

    def close_shutter(self, block_until_complete: bool = True) -> None:
        self.shutter = "Closed"

    def xray_off(self) -> None:
        self.kv, self.ma = 0.0, 0.0

    def get_xray_readbacks(self) -> Dict[str, float]:
        return {
            "voltage_kv": self.kv,
            "current_ma": self.ma,
            "voltage_setpoint_kv": self.kv,
            "current_setpoint_ma": self.ma,
            "filament_current": 0.0,
            "filament_current_limit": 0.0,
            "filament_current_preheat": 0.0,
        }


@dataclass
class SimHandles:
    mono: FakeMono
    ketek: FakeKetek
    wafer_stage: FakeWaferStage
    xchanger: FakeXchanger
    proto: FakeProto
    state_dir: str


def _mod(name: str, **attrs: Any) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


class _Base:
    """Stand-in for pyarcus.ArcusController / NanotecController."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass


class _QCoreApplication:
    @staticmethod
    def instance() -> None:
        return None


def _install_fake_modules() -> None:
    api = _mod("pyarcus.api", get_number_of_devices=lambda: 0)
    pa = _mod("pyarcus", ArcusController=_Base, api=api)
    sys.modules["pyarcus"] = pa
    iface = _mod("handel.interface")
    cffi = _mod("handel._cffi")
    _mod("handel", interface=iface, _cffi=cffi)
    _mod("ticcontrol")
    drv = _mod("nanotec_control.nanotec_driver", NanotecController=_Base)
    _mod("nanotec_control", nanotec_driver=drv)
    _mod("pyprotohv", proto_controller=None)
    _mod("spellman_usb")
    _mod("zwo_efw")
    qtcore = _mod("PySide2.QtCore", QCoreApplication=_QCoreApplication)
    _mod("PySide2", QtCore=qtcore)


def install_sim(state_dir: str) -> SimHandles:
    root = Path(state_dir)
    for sub in ("temp", "home"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(root / "temp")
    os.environ["HOMEDRIVE"] = str(root / "home")
    os.environ["HOMEPATH"] = "home"

    _install_fake_modules()

    import easyxafs.monochromator
    import easyxafs.scan
    import easyxafs.wafer_stage_motor_control
    import easyxafs.xchanger_control

    mono = FakeMono()
    ketek = FakeKetek(mono)
    wafer = FakeWaferStage()
    xch = FakeXchanger()
    proto = FakeProto()

    easyxafs.monochromator.mono = mono
    easyxafs.scan.mono = mono
    easyxafs.scan.sdd_detector = ketek
    easyxafs.wafer_stage_motor_control.wafer_stage = wafer
    easyxafs.xchanger_control.xchanger = xch
    sys.modules["pyprotohv"].proto_controller = proto
    return SimHandles(mono, ketek, wafer, xch, proto, str(root))
