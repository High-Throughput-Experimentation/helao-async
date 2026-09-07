"""Wavelength calibration from a calibration-lamp measurement.

Pure numerics and persistence: no vendor SDK, no HELAO server imports. A
station that derives its wavelength axis from a lamp instead of from an
ATSpectrograph reads its axis from here.

Coefficients are persisted rather than a materialized array. The record is
small, diagnosable by eye in a station's STATES directory, and carries
``fit_rms_nm`` so a gate has a number to assert on. The cost is that a change
in functional form orphans existing records -- which is why ``model`` is
stored and why ``load`` refuses a value it does not recognize instead of
mis-evaluating a record it does not understand.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Optional, Sequence

import numpy as np

MODEL_POLY: Final[str] = "poly"

#: Chebyshev coefficients over a normalised pixel domain -- what `wl_fit`
#: produces. A raw-power fit of the same order over a 2560-wide detector
#: carries terms of order 4e13, which conditions badly and reads as noise on
#: the page. `poly` is still evaluated so records written before the change
#: keep loading.
MODEL_CHEB: Final[str] = "cheb"


class UnknownCalibrationModel(Exception):
    """A persisted record names a functional form this build cannot evaluate."""


@dataclass(frozen=True)
class WavelengthCalibration:
    """A pixel-to-nanometre mapping and the provenance of its fit."""

    model: str
    coeffs: list[float]
    n_pixels: int
    fit_rms_nm: float
    n_lines: int
    lamp: str
    created: str
    source_action_uuid: Optional[str]
    #: Pixel range the Chebyshev basis is normalised over. `None` means the
    #: whole detector, which is what every fit this code produces uses; it is
    #: a field rather than an assumption so a record stays evaluable if a
    #: future fit is ever restricted to part of the array.
    domain: Optional[list[float]] = None
    #: `air` or `vacuum`. Which one is not recoverable from the numbers -- the
    #: two conventions differ by ~0.03%, about 0.2 nm at 700 nm, which is
    #: larger than the fit residual and invisible without this field.
    medium: str = "unknown"
    #: Lines discarded by sigma-clipping, and lines dropped for reaching
    #: saturation. Both are how a fit that succeeded on too little evidence is
    #: told apart from one that succeeded on plenty.
    n_rejected: int = 0
    n_saturated: int = 0
    #: The worst single residual. RMS alone hides one badly-placed line among
    #: many good ones.
    max_residual_nm: float = 0.0
    #: Which variant wrote this record: ``"calibration"`` if the fit is that
    #: station's live wavelength axis, ``"spectrograph"`` if it was recorded
    #: only to compare against ``GetCalibration``. Defaulted because records
    #: written before this field existed carry no value at all, and the
    #: station that wrote one is not going to be re-calibrated just to gain a
    #: string -- see ``load``.
    wl_source: str = "unknown"


def evaluate(calib: WavelengthCalibration) -> np.ndarray:
    """The wavelength array this calibration describes, one entry per pixel."""
    pixels = np.arange(calib.n_pixels, dtype=float)
    if calib.model == MODEL_CHEB:
        domain = calib.domain or [0.0, float(calib.n_pixels - 1)]
        return np.polynomial.chebyshev.Chebyshev(calib.coeffs, domain=domain)(pixels)
    if calib.model == MODEL_POLY:
        return np.polyval(list(reversed(calib.coeffs)), pixels)
    raise UnknownCalibrationModel(calib.model)


def is_monotonic(arr) -> bool:
    """Whether ``arr`` increases, or decreases, strictly across its length.

    A real wavelength axis is one or the other: pixels map onto the detector
    in order. A fit that doubles back describes an axis on which two pixels
    claim the same wavelength, which is not a calibration at all -- and it
    plots as a perfectly plausible spectrum, so nothing downstream will ever
    catch it. Its own function so it can be tested without a camera.
    """
    values = np.asarray(arr, dtype=float)
    if values.size < 2:
        return True
    deltas = np.diff(values)
    # `not (a or b)` rather than `a and b`: a NaN makes both comparisons
    # False, so a fit that produced one is refused rather than accepted.
    return bool(np.all(deltas > 0) or np.all(deltas < 0))


def save(calib: WavelengthCalibration, path: Path) -> None:
    """Write the calibration as indented JSON, atomically, keeping one backup.

    The outgoing record is copied to a sibling ``<name>.prev`` first. An
    overwrite is otherwise irreversible, and the thing being overwritten is a
    calibration that was, as far as anyone knows, good -- while the thing
    overwriting it has only just been measured. One generation is enough to
    put a station back where it was; a rolling history would be a filing
    system nobody asked for.

    Backing up is a copy, not a rename, so a failure between the two steps
    leaves the live calibration in place rather than removed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        prev = path.with_name(path.name + ".prev")
        prev_tmp = path.with_name(f".{prev.name}.tmp")
        prev_tmp.write_bytes(path.read_bytes())
        prev_tmp.replace(prev)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(asdict(calib), indent=2) + "\n")
    tmp.replace(path)


def load(path: Path) -> WavelengthCalibration:
    """Read a calibration, refusing a model this build cannot evaluate."""
    raw = json.loads(path.read_text())
    if raw.get("model") not in (MODEL_CHEB, MODEL_POLY):
        raise UnknownCalibrationModel(
            f"{raw.get('model')!r} in {path}; this build evaluates "
            f"{MODEL_CHEB!r} and {MODEL_POLY!r}"
        )
    return WavelengthCalibration(
        model=raw["model"],
        coeffs=[float(c) for c in raw["coeffs"]],
        n_pixels=int(raw["n_pixels"]),
        fit_rms_nm=float(raw["fit_rms_nm"]),
        n_lines=int(raw["n_lines"]),
        lamp=str(raw["lamp"]),
        created=str(raw["created"]),
        source_action_uuid=raw.get("source_action_uuid"),
        # Absent on every record written before the field existed. Defaulted
        # rather than required: a station that legitimately calibrated last
        # month must keep loading, and "unknown" is exactly what a reader
        # should be told about it.
        wl_source=str(raw.get("wl_source", "unknown")),
        # All absent on pre-Chebyshev records. A `poly` record has no domain
        # (it is evaluated in raw pixels) and no medium anyone recorded, so
        # "unknown" is the honest reading rather than a guess at "air".
        domain=(
            [float(x) for x in raw["domain"]] if raw.get("domain") is not None else None
        ),
        medium=str(raw.get("medium", "unknown")),
        n_rejected=int(raw.get("n_rejected", 0)),
        n_saturated=int(raw.get("n_saturated", 0)),
        max_residual_nm=float(raw.get("max_residual_nm", 0.0)),
    )


def calibration_path(states_root: str, host: str, server_key: str) -> Path:
    """``<STATES>/<host>_<server_key>_andor_wl_calib.json``.

    Follows the convention ``JsonFileCalibrationStore`` uses for the Galil
    plate calibration, with ``server_key`` added because one host can run more
    than one andor server.
    """
    return Path(states_root) / f"{host}_{server_key}_andor_wl_calib.json"


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
