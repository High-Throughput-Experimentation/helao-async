"""JsonFileCalibrationStore behavior-parity tests (P3a galil-split slice-2).

Proves byte-format parity with the legacy `galil_motion_driver.py`
`save_transfermatrix`/`load_transfermatrix` (JSON via
`json.dumps(matrix.tolist())`, read back via `json.loads(f.readline())`) and
the exact filename conventions used by the driver's `connect()`:
- `<states_root>/<host>_last_plate_calib.json`
- `<db_root>/plate_calib/<host>_instrument_calib.json`
"""

import json
import os

import numpy as np
import pytest

from helao.hexagon.adapters.legacy.calibration_store import JsonFileCalibrationStore
from helao.hexagon.ports.calibration_store import CalibrationStorePort

HOSTNAME = "teststation"


def test_is_calibration_store_port(tmp_path):
    store = JsonFileCalibrationStore(str(tmp_path), str(tmp_path), HOSTNAME)
    assert isinstance(store, CalibrationStorePort)


def test_round_trip_plate_calibration_exact_filename_and_format(tmp_path):
    states_root = tmp_path / "STATES"
    states_root.mkdir()
    store = JsonFileCalibrationStore(str(states_root), str(tmp_path), HOSTNAME)

    matrix = np.matrix([[1, 0, 5], [0, 1, 7], [0, 0, 1]])
    store.save_plate_calibration(matrix)

    expected_path = states_root / f"{HOSTNAME}_last_plate_calib.json"
    assert expected_path.exists(), "expected exact legacy filename convention"

    # Byte-format parity with legacy `save_transfermatrix`: a bare
    # `json.dumps(matrix.tolist())` write (no trailing newline / extra keys).
    raw = expected_path.read_text()
    assert raw == json.dumps(matrix.tolist())

    # Parity with legacy `load_transfermatrix`: `json.loads(f.readline())`.
    with open(expected_path, "r") as f:
        loaded = json.loads(f.readline())
    assert loaded == matrix.tolist()

    round_tripped = store.load_plate_calibration()
    assert round_tripped is not None
    assert np.array_equal(round_tripped, matrix)


def test_save_plate_calibration_creates_missing_parent_dir(tmp_path):
    states_root = tmp_path / "nested" / "STATES"
    store = JsonFileCalibrationStore(str(states_root), str(tmp_path), HOSTNAME)

    matrix = np.matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    store.save_plate_calibration(matrix)

    expected_path = states_root / f"{HOSTNAME}_last_plate_calib.json"
    assert expected_path.exists()


def test_load_plate_calibration_returns_none_when_file_absent(tmp_path):
    states_root = tmp_path / "STATES"
    states_root.mkdir()
    store = JsonFileCalibrationStore(str(states_root), str(tmp_path), HOSTNAME)

    assert store.load_plate_calibration() is None


def test_load_plate_calibration_returns_none_on_wrong_shape(tmp_path):
    states_root = tmp_path / "STATES"
    states_root.mkdir()
    store = JsonFileCalibrationStore(str(states_root), str(tmp_path), HOSTNAME)

    bad_path = states_root / f"{HOSTNAME}_last_plate_calib.json"
    bad_path.write_text(json.dumps([[1, 0], [0, 1]]))

    assert store.load_plate_calibration() is None


def test_load_instrument_calibration_exact_path(tmp_path):
    db_root = tmp_path / "DB"
    calib_dir = db_root / "plate_calib"
    calib_dir.mkdir(parents=True)

    matrix = np.matrix([[1, 0, 2], [0, 1, 3], [0, 0, 1]])
    instrument_file = calib_dir / f"{HOSTNAME}_instrument_calib.json"
    instrument_file.write_text(json.dumps(matrix.tolist()))

    store = JsonFileCalibrationStore(str(tmp_path), str(db_root), HOSTNAME)
    loaded = store.load_instrument_calibration()

    assert loaded is not None
    assert np.array_equal(loaded, matrix)


def test_load_instrument_calibration_returns_none_when_file_absent(tmp_path):
    db_root = tmp_path / "DB"
    (db_root / "plate_calib").mkdir(parents=True)
    store = JsonFileCalibrationStore(str(tmp_path), str(db_root), HOSTNAME)

    assert store.load_instrument_calibration() is None


def test_save_plate_calibration_is_noop_when_states_root_is_none(tmp_path):
    store = JsonFileCalibrationStore(None, str(tmp_path), HOSTNAME)
    matrix = np.matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    # Should not raise: mirrors legacy `save_transfermatrix`'s `if file is
    # not None` no-op guard.
    store.save_plate_calibration(matrix)


def test_load_plate_calibration_raises_typeerror_when_states_root_is_none(tmp_path):
    # Mirrors legacy `load_transfermatrix`, which is NOT guarded against a
    # None path (`os.path.exists(None)` raises TypeError); the driver's
    # `connect()` only ever reaches this from inside its own try/except.
    store = JsonFileCalibrationStore(None, str(tmp_path), HOSTNAME)
    with pytest.raises(TypeError):
        store.load_plate_calibration()
