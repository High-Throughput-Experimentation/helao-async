"""NativeGalilMotion (the class stations run): a failed move must not wedge the
stage, and a reconnect must not overwrite an unreadable plate calibration with
identity."""

import types

import numpy as np
import pytest

from helao.hexagon.adapters.native import galil_motion_native as gmn
from helao.hexagon.adapters.native.galil_motion_native import NativeGalilMotion


class _Channel:
    def __init__(self):
        self.commands = []

    def open(self, s):
        pass

    def command(self, cmd):
        self.commands.append(cmd)
        return "0"

    def close(self):
        pass


class _Active:
    def __init__(self, params):
        self.action = types.SimpleNamespace(action_params=params)


@pytest.mark.asyncio
async def test_failed_move_clears_blocked_and_motor_busy():
    drv = NativeGalilMotion({"axis_id": {"x": "A"}}, channel=_Channel())
    drv.galil_enabled = True
    drv.transform = object()  # past the guard; the bad mode raises first
    with pytest.raises(ValueError):
        await drv.motor_move(
            _Active({"d_mm": [1.0], "axis": ["x"], "mode": "not-a-mode"})
        )
    assert drv.blocked is False
    assert drv.motor_busy is False


def test_connect_keeps_unreadable_plate_calibration(tmp_path, monkeypatch):
    monkeypatch.setattr(gmn, "gethostname", lambda: "TESTHOST")
    drv = NativeGalilMotion(
        {"axis_id": {"x": "A"}},  # no galil_ip_str: no I/O
        channel=_Channel(),
        base_hook=types.SimpleNamespace(
            helaodirs=types.SimpleNamespace(states_root=str(tmp_path), db_root=None)
        ),
    )
    calib = tmp_path / "testhost_last_plate_calib.json"
    calib.write_text("[[1, 0, 0], [0, 1, 0]\n", encoding="utf-8")  # truncated
    drv.connect()
    assert calib.read_text(encoding="utf-8") == "[[1, 0, 0], [0, 1, 0]\n"
    assert np.array_equal(drv.plate_transfermatrix, drv.dflt_matrix)
