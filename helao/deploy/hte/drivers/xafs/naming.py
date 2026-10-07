"""Pure helpers for xafs savenames and wafer-stage coordinates.

Savenames must match the converter regex
``^(.*?)_(Scan\\d{4}_Sample\\d+_)?(X[-.\\d]+_Y[-.\\d]+|EnergyCalib.*?|IzeroRef.*?)_\\d{3}_exd\\.csv\\.zip$``;
the sidecar appends ``_{counter:03d}_exd.csv.zip``.
"""

from typing import List, Tuple

_REF_TAG = {"energy_calib": "EnergyCalib", "izero": "IzeroRef"}


def sample_savename(
    element: str, scan_index: int, sample_no: int, x: float, y: float
) -> str:
    return f"{element}_Scan{scan_index:04d}_Sample{sample_no:d}_X{x:.3f}_Y{y:.3f}"


def reference_savename(element: str, run_use: str, name: str) -> str:
    if run_use not in _REF_TAG:
        raise ValueError(f"run_use {run_use!r} is not a reference (energy_calib, izero)")
    return f"{element}_{_REF_TAG[run_use]}_{name}"


def apply_affine(m: List[List[float]], px: float, py: float) -> Tuple[float, float]:
    """Apply a 2x3 affine matrix to a plate-frame point."""
    return (
        m[0][0] * px + m[0][1] * py + m[0][2],
        m[1][0] * px + m[1][1] * py + m[1][2],
    )

