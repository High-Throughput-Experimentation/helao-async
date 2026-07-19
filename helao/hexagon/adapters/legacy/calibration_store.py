"""JsonFileCalibrationStore adapter (P3a galil-split slice-2): the JSON-file
CalibrationStorePort backing the Galil motion driver's plate/instrument
calibration matrices.

Reproduces `galil_motion_driver.py`'s `save_transfermatrix`/
`load_transfermatrix` file I/O verbatim, including its edge-case quirks:
- `save_*`: no-op when the target path is None (parent dir created via
  `os.makedirs(..., exist_ok=True)`, write is `json.dumps(matrix.tolist())`).
- `load_*`: NOT guarded against a None path -- `os.path.exists(None)` raises
  `TypeError`, matching the legacy method (callers only ever reach this with
  a None path from within `connect()`'s outer `try/except`, which is where
  the legacy code lets that same TypeError get caught).
- shape-checked against the plate matrix's fixed (3, 3) default
  (`dflt_matrix = np.matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])`); None on
  missing/malformed/wrong-shape file.

Boundary note: mirrors `state_persistence.py`/`sample_state.py` -- constructed
with plain values (states_root, db_root, hostname), no deployment-tree
import at module top.
"""

import json
import os
from typing import Optional

import numpy as np

__all__ = ["JsonFileCalibrationStore"]

_DFLT_SHAPE = (3, 3)


class JsonFileCalibrationStore:
    def __init__(
        self,
        states_root: Optional[str],
        db_root: Optional[str],
        hostname: str,
    ):
        self._states_root = states_root
        self._db_root = db_root
        self._hostname = hostname

    def _plate_path(self) -> Optional[str]:
        if self._states_root is None:
            return None
        return os.path.join(
            self._states_root, f"{self._hostname}_last_plate_calib.json"
        )

    def _instrument_path(self) -> str:
        # Not guarded against `self._db_root is None`: matches legacy
        # `connect()`, which builds this path unguarded inside `if helaodirs
        # is not None:` and lets a TypeError from a None db_root propagate.
        return os.path.join(
            self._db_root,  # type: ignore[arg-type]
            "plate_calib",
            f"{self._hostname}_instrument_calib.json",
        )

    def load_plate_calibration(self) -> Optional[np.matrix]:
        return self._read_matrix(self._plate_path())

    def save_plate_calibration(self, matrix: np.matrix) -> None:
        self._write_matrix(self._plate_path(), matrix)

    def load_instrument_calibration(self) -> Optional[np.matrix]:
        return self._read_matrix(self._instrument_path())

    @staticmethod
    def _write_matrix(file: Optional[str], matrix: np.matrix) -> None:
        """Write `matrix` to `file` as JSON; no-op when `file` is None."""
        if file is not None:
            filedir, _ = os.path.split(file)
            if not os.path.exists(filedir):
                os.makedirs(filedir, exist_ok=True)

            with open(file, "w") as f:
                f.write(json.dumps(matrix.tolist()))

    @staticmethod
    def _read_matrix(file: Optional[str]) -> Optional[np.matrix]:
        """Read a JSON-encoded matrix from `file`.

        Returns None if the file is missing, malformed, or the wrong shape.
        Not guarded against `file is None` -- matches legacy
        `load_transfermatrix`, whose only caller reaches this with a None
        path from inside `connect()`'s outer `try/except`.
        """
        if os.path.exists(file):  # type: ignore[arg-type]
            with open(file, "r") as f:  # type: ignore[arg-type]
                try:
                    data = f.readline()
                    new_matrix = np.matrix(json.loads(data))
                    if new_matrix.shape != _DFLT_SHAPE:
                        return None
                    return new_matrix
                except Exception:
                    return None
        else:
            return None
