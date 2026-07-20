"""CalibrationStorePort (P3a galil-split slice-2): plate/instrument
calibration matrix file I/O for the Galil motion driver, promoted to a port.

Legacy behavior reproduced verbatim (`galil_motion_driver.py`
`save_transfermatrix`/`load_transfermatrix`, `connect()` lines 169-196):
- plate calibration lives at `<states_root>/<host>_last_plate_calib.json`.
- instrument calibration lives at
  `<db_root>/plate_calib/<host>_instrument_calib.json`.
- on-disk format is `json.dumps(matrix.tolist())` (an `np.matrix`), read back
  via `json.loads(f.readline())`.

Only these three legacy calibration-file operations are in scope for this
slice. The aligner's named-plate write (`<db_root>/plate_calib/<host>_plate_
<plateid>_calib.json`, `aligner.py:1172`) is an arbitrary out-of-scope path
handed to the driver's still-generic `save_transfermatrix(file=...)` method
and is deferred to slice-3.

Boundary note (spec §4.1, locked): ports/ may only import stdlib +
`helao.hexagon.domain`/`ports` + the declared `helao_driver` exception --
numpy is a domain-layer-only third party (per `auxiliary.py`'s `PlateInfoPort`
precedent of typing a disallowed third-party return as a plain generic), so
the matrix type below is `Any` rather than an actual `np.matrix` import.
Concretely it is always an `np.matrix`, per the module docstring above.
"""

from typing import Any, Optional, Protocol, runtime_checkable

__all__ = ["CalibrationStorePort"]


@runtime_checkable
class CalibrationStorePort(Protocol):
    """Plate/instrument calibration matrix persistence for the Galil driver."""

    def load_plate_calibration(self) -> Optional[Any]:
        """Read `<host>_last_plate_calib.json` under states_root.

        Returns an `np.matrix`, or None if the file is missing, malformed,
        or the wrong shape.
        """
        ...

    def save_plate_calibration(self, matrix: Any) -> None:
        """Write `matrix` (an `np.matrix`) to `<host>_last_plate_calib.json`
        under states_root."""
        ...

    def load_instrument_calibration(self) -> Optional[Any]:
        """Read `plate_calib/<host>_instrument_calib.json` under db_root.

        Returns an `np.matrix`, or None if the file is missing, malformed,
        or the wrong shape.
        """
        ...
