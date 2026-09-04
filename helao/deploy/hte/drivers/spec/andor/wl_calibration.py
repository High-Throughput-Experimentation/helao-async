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

#: Minimum reference lines required above the polynomial degree. A fit with
#: exactly degree+1 points interpolates and reports rms 0, which reads as a
#: perfect calibration and is no evidence at all.
MIN_EXCESS_LINES: Final[int] = 1


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


def evaluate(calib: WavelengthCalibration) -> np.ndarray:
    """The wavelength array this calibration describes, one entry per pixel."""
    if calib.model != MODEL_POLY:
        raise UnknownCalibrationModel(calib.model)
    pixels = np.arange(calib.n_pixels, dtype=float)
    return np.polyval(list(reversed(calib.coeffs)), pixels)


def find_peaks(counts: Sequence[float], n_expected: int) -> list[float]:
    """The ``n_expected`` strongest local maxima, as sub-pixel centroids.

    Deliberately simple: a parabolic refinement of the strongest well-separated
    local maxima. Replace this with the station's own peak finder by editing
    this function alone -- ``fit_wavelength`` is its only caller.
    """
    arr = np.asarray(counts, dtype=float)
    if arr.ndim != 1:
        raise ValueError("counts must be one-dimensional")
    interior = np.arange(1, arr.size - 1)
    is_max = (arr[interior] > arr[interior - 1]) & (arr[interior] >= arr[interior + 1])
    candidates = interior[is_max]
    candidates = candidates[np.argsort(arr[candidates])[::-1]]

    chosen: list[int] = []
    for c in candidates:
        if all(abs(c - k) > 5 for k in chosen):
            chosen.append(int(c))
        if len(chosen) == n_expected:
            break
    chosen.sort()

    refined: list[float] = []
    for c in chosen:
        y0, y1, y2 = arr[c - 1], arr[c], arr[c + 1]
        denom = y0 - 2.0 * y1 + y2
        offset = 0.0 if denom == 0 else 0.5 * (y0 - y2) / denom
        refined.append(c + float(offset))
    return refined


def fit_wavelength(
    counts: Sequence[float],
    lamp_lines_nm: Sequence[float],
    *,
    degree: int = 3,
    lamp: str = "unknown",
    source_action_uuid: Optional[str] = None,
) -> WavelengthCalibration:
    """Fit pixel-to-nm from a lamp spectrum and its known reference lines.

    Args:
        counts: The measured lamp spectrum, one value per detector pixel.
        lamp_lines_nm: Known wavelengths of the lamp's lines, ascending. One
            peak is located per entry.
        degree: Polynomial degree.
        lamp: Free-text lamp identifier, recorded in the calibration.
        source_action_uuid: The action that produced ``counts``, if any.

    Returns:
        A :class:`WavelengthCalibration` whose ``fit_rms_nm`` is the residual
        of the located peaks against ``lamp_lines_nm``.

    Raises:
        ValueError: If ``degree`` leaves too few lines to be evidence, or if
            the expected number of peaks could not be located.
    """
    lines = sorted(float(x) for x in lamp_lines_nm)
    if len(lines) < degree + 1 + MIN_EXCESS_LINES:
        raise ValueError(
            f"degree {degree} needs at least {degree + 1 + MIN_EXCESS_LINES} "
            f"reference lines; got {len(lines)}"
        )

    peaks = find_peaks(counts, len(lines))
    if len(peaks) != len(lines):
        raise ValueError(
            f"located {len(peaks)} peak(s) for {len(lines)} reference line(s)"
        )

    coeffs_desc = np.polyfit(np.array(peaks), np.array(lines), degree)
    residuals = np.polyval(coeffs_desc, np.array(peaks)) - np.array(lines)
    return WavelengthCalibration(
        model=MODEL_POLY,
        coeffs=[float(c) for c in reversed(coeffs_desc)],
        n_pixels=len(counts),
        fit_rms_nm=float(np.sqrt(np.mean(residuals**2))),
        n_lines=len(lines),
        lamp=lamp,
        created=_utc_now(),
        source_action_uuid=source_action_uuid,
    )


def save(calib: WavelengthCalibration, path: Path) -> None:
    """Write the calibration as indented JSON, atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(asdict(calib), indent=2) + "\n")
    tmp.replace(path)


def load(path: Path) -> WavelengthCalibration:
    """Read a calibration, refusing a model this build cannot evaluate."""
    raw = json.loads(path.read_text())
    if raw.get("model") != MODEL_POLY:
        raise UnknownCalibrationModel(
            f"{raw.get('model')!r} in {path}; this build evaluates {MODEL_POLY!r}"
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
