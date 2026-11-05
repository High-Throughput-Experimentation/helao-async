"""Fit a wavelength solution from a calibration-lamp exposure.

The standard arc-lamp procedure from the IRAF ``identify``/``reidentify``
lineage, which is what optical spectroscopy does for this: detect emission
lines, centroid them to sub-pixel accuracy, identify each against a catalogue,
fit a low-order polynomial, and reject the mis-identifications iteratively.

Pure numerics. No vendor SDK, no HELAO server imports, no camera -- the whole
pipeline runs against an array of counts, so it is testable on Linux with
nothing attached. ``wl_calibration`` holds the record this produces; this
module holds how it is produced.

Four choices here follow the field rather than the obvious shortcut, and each
one is load-bearing:

- **Peaks are found by prominence, not height.** A lamp exposure sits on a
  sloping background, so a height threshold either misses lines at the dim end
  or admits background at the bright end. Prominence measures a peak against
  its own surroundings and is what ``find_peaks`` is for.
- **Centroids come from a Gaussian fit**, not from the peak sample. A line
  lands between pixels, and the integer index is wrong by up to half a pixel
  -- which at a typical dispersion is a tenth of a nanometre, an order of
  magnitude above what the fit residual should be. This is the part
  ``scipy.optimize`` is actually needed for; the polynomial itself is linear
  least squares.
- **The polynomial is Chebyshev on a normalised pixel coordinate.** A 4th
  order fit in raw pixels over a 2560-wide detector carries terms of order
  2560**4, about 4e13. The normal equations are then badly conditioned and the
  coefficients mean nothing to a reader. IRAF defaults to Chebyshev or
  Legendre for exactly this reason.
- **The fit is sigma-clipped, iteratively.** One line matched to the wrong
  catalogue entry does not announce itself: it bends the solution slightly
  everywhere rather than failing. Clipping is what finds it.

Two things this deliberately does not do. It does not weight the fit by line
intensity -- a bright line is not a better-measured line, and a saturated one
is a worse one, so the catalogue's intensities are used to choose which lines
to expect, never to weight. And it does not identify lines from nothing: the
caller supplies anchors, because automatic identification from a bare spectrum
is the step that fails silently and expensively.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Optional, Sequence

import numpy as np
import numpy.typing as npt

from .kr_lines import KR_LINES_AIR_NM, LAMP_NAME, LAMP_RANGE_NM, MEDIUM
from .wl_calibration import MODEL_CHEB, WavelengthCalibration, _utc_now

#: Half-width of the window a line is centroided over, in pixels. Wide enough
#: to carry the wings a Gaussian needs, narrow enough not to swallow a
#: neighbour at the dispersions this instrument runs at.
CENTROID_HALF_WIDTH_PX: Final[int] = 4

#: A catalogue line closer than this to its neighbour is dropped before
#: matching. The two blend into one peak whose centroid sits between them, and
#: a centroid between two lines matched to either one drags the fit by half
#: their separation. Krypton has such pairs at 431.781/431.855 nm and
#: 642.018/642.103 nm.
DEFAULT_MIN_SEPARATION_NM: Final[float] = 0.25

#: Residual beyond which a matched line is discarded and the fit repeated,
#: in units of the residual standard deviation.
DEFAULT_SIGMA_CLIP: Final[float] = 3.0

#: Lines must exceed the polynomial's own degrees of freedom by this much
#: before a fit means anything. At exactly degree+1 the polynomial
#: interpolates and reports zero residual, which reads as perfect and is no
#: evidence at all.
MIN_EXCESS_LINES: Final[int] = 3


class CalibrationFitError(Exception):
    """The exposure or the anchors do not support a wavelength solution."""


@dataclass(frozen=True)
class LineCentroid:
    """One detected emission line, located to sub-pixel accuracy."""

    pixel: float
    sigma_px: float
    amplitude: float
    #: True when the profile reached ``saturation``. Kept rather than dropped
    #: at detection so the caller can report how many lines were lost to it --
    #: a calibration that failed because every strong line was saturated
    #: should say so, not just report too few lines.
    saturated: bool


@dataclass(frozen=True)
class MatchedLine:
    """A detected centroid identified with a catalogue wavelength."""

    pixel: float
    wavelength_nm: float
    intensity: int
    species: str


def detect_peaks(
    counts: npt.ArrayLike,
    *,
    prominence: Optional[float] = None,
    min_distance_px: int = 4,
    background_window_px: int = 51,
) -> np.ndarray:
    """Indices of emission lines in ``counts``, by prominence.

    ``prominence`` defaults to five times a robust noise estimate taken from
    the residual against a running median, so it adapts to the exposure
    instead of needing an absolute count re-tuned per integration time. The
    running median is what makes it survive a sloping background.
    """
    from scipy.ndimage import median_filter
    from scipy.signal import find_peaks

    arr = np.asarray(counts, dtype=float)
    if arr.ndim != 1:
        raise CalibrationFitError(f"counts must be 1-D, got shape {arr.shape}")
    if prominence is None:
        # Estimate the noise from the residual against a running median, not
        # from the raw signal. A lamp frame sits on a sloping background, and
        # the MAD of the raw counts measures that slope rather than the noise
        # -- on a frame ramping over a few thousand counts it returns a
        # threshold larger than any line, and find_peaks then reports nothing
        # at all. The median filter removes the trend and leaves the lines,
        # which are far narrower than its window.
        background = median_filter(arr, size=background_window_px, mode="nearest")
        residual = arr - background
        mad = float(np.median(np.abs(residual - np.median(residual))))
        # 1.4826 converts a MAD to a Gaussian-equivalent sigma.
        noise = 1.4826 * mad
        # A frame with no noise at all -- only ever a synthetic one -- has
        # MAD 0 and needs some other scale. Not the range: a single hot pixel
        # sets the range and would push the threshold above every real line,
        # which is exactly how a cosmic ray blinds the detector to the
        # spectrum underneath it. A high percentile is set by the line
        # population instead, and one outlier cannot move it.
        prominence = (
            5.0 * noise if noise > 0 else 0.05 * float(np.percentile(residual, 99))
        )
    if prominence <= 0:
        raise CalibrationFitError("exposure is featureless: no peaks to find")
    peaks, _ = find_peaks(arr, prominence=prominence, distance=min_distance_px)
    return peaks


def centroid_peaks(
    counts: npt.ArrayLike,
    indices: npt.ArrayLike,
    *,
    half_width_px: int = CENTROID_HALF_WIDTH_PX,
    saturation: Optional[float] = None,
) -> list[LineCentroid]:
    """Refine integer peak indices to sub-pixel centroids by Gaussian fit.

    Each line is fitted as a Gaussian on a linear background over a window of
    ``2 * half_width_px + 1`` samples. A line whose fit does not converge, or
    whose fitted centre leaves its own window, is dropped -- that is a blend
    or an edge artefact, not a line.
    """
    from scipy.optimize import curve_fit

    arr = np.asarray(counts, dtype=float)
    out: list[LineCentroid] = []
    for idx in np.asarray(indices).tolist():
        lo = max(0, int(idx) - half_width_px)
        hi = min(arr.size, int(idx) + half_width_px + 1)
        if hi - lo < 5:
            continue  # too close to an edge to constrain four parameters
        x = np.arange(lo, hi, dtype=float)
        y = arr[lo:hi]
        peak_height = float(y.max())
        base = float(y.min())
        guess = [peak_height - base, float(idx), 1.5, base]
        try:
            popt, _ = curve_fit(_gaussian_on_a_line, x, y, p0=guess, maxfev=2000)
        except (RuntimeError, ValueError):
            continue
        amplitude, centre, sigma, _slope_free = popt[0], popt[1], abs(popt[2]), popt[3]
        if not (lo <= centre <= hi - 1):
            continue
        if not np.isfinite([amplitude, centre, sigma]).all():
            continue
        if sigma <= 0 or sigma > half_width_px:
            continue
        out.append(
            LineCentroid(
                pixel=float(centre),
                sigma_px=float(sigma),
                amplitude=float(amplitude),
                saturated=saturation is not None and peak_height >= saturation,
            )
        )
    return out


def _gaussian_on_a_line(x, amplitude, centre, sigma, background):
    """A Gaussian over a flat background, the standard emission-line profile."""
    return background + amplitude * np.exp(-0.5 * ((x - centre) / sigma) ** 2)


def usable_catalogue(
    lines: Sequence[tuple[float, int, str]] = tuple(KR_LINES_AIR_NM),
    *,
    lo_nm: float = LAMP_RANGE_NM[0],
    hi_nm: float = LAMP_RANGE_NM[1],
    min_intensity: int = 0,
    min_separation_nm: float = DEFAULT_MIN_SEPARATION_NM,
) -> list[tuple[float, int, str]]:
    """Catalogue lines a given exposure can be expected to resolve.

    Drops anything outside the range, below the intensity floor, or too close
    to a neighbour to be seen as a separate peak. Separation is judged against
    the *unfiltered* neighbours: a faint line still blends with a bright one,
    so removing the faint one first would leave the bright one looking
    isolated when it is not.
    """
    ordered = sorted(lines)
    isolated: list[tuple[float, int, str]] = []
    for i, entry in enumerate(ordered):
        wl = entry[0]
        left = ordered[i - 1][0] if i else None
        right = ordered[i + 1][0] if i + 1 < len(ordered) else None
        if left is not None and wl - left < min_separation_nm:
            continue
        if right is not None and right - wl < min_separation_nm:
            continue
        isolated.append(entry)
    return [e for e in isolated if lo_nm <= e[0] <= hi_nm and e[1] >= min_intensity]


def _snap_anchor_wavelength(
    wavelength_nm: float,
    catalogue: Sequence[tuple[float, int, str]],
    tolerance_nm: float,
) -> float:
    """The catalogue line an operator's approximate anchor refers to.

    An operator reads a wavelength off a chart or off memory; the catalogue
    knows it to four decimals. Snapping means the anchors that seed the whole
    solution carry the catalogue's precision, not the operator's. Refusing
    beyond the tolerance is deliberate -- an anchor that matches no line is
    far more likely to be a misread than a discovery.
    """
    if not catalogue:
        raise CalibrationFitError("no catalogue lines to snap anchors to")
    wavelengths = np.array([c[0] for c in catalogue])
    i = int(np.argmin(np.abs(wavelengths - wavelength_nm)))
    nearest = float(wavelengths[i])
    if abs(nearest - wavelength_nm) > tolerance_nm:
        raise CalibrationFitError(
            f"anchor {wavelength_nm} nm matches no catalogue line within "
            f"{tolerance_nm} nm (nearest is {nearest} nm). Either the "
            f"wavelength is misread, or that line was dropped as too close "
            f"to a neighbour to resolve -- pick an isolated line instead."
        )
    return nearest


def _snap_anchor_pixel(
    pixel: float, centroids: Sequence[LineCentroid], tolerance_px: float
) -> float:
    """The detected line an operator's approximate anchor pixel refers to."""
    if not centroids:
        raise CalibrationFitError("no lines were detected in this exposure")
    pixels = np.array([c.pixel for c in centroids])
    i = int(np.argmin(np.abs(pixels - pixel)))
    nearest = float(pixels[i])
    if abs(nearest - pixel) > tolerance_px:
        raise CalibrationFitError(
            f"anchor at pixel {pixel} has no detected line within "
            f"{tolerance_px} px (nearest is {nearest:.2f})"
        )
    return nearest


def _fit_chebyshev(
    pixels: np.ndarray, wavelengths: np.ndarray, degree: int, domain: list[float]
) -> np.ndarray:
    """Least-squares Chebyshev coefficients over a normalised pixel domain."""
    return np.polynomial.chebyshev.Chebyshev.fit(
        pixels, wavelengths, deg=degree, domain=domain
    ).coef


def fit_wavelength(
    counts: npt.ArrayLike,
    anchors: Sequence[tuple[float, float]],
    *,
    degree: int = 4,
    catalogue: Optional[Sequence[tuple[float, int, str]]] = None,
    match_tolerance_px: float = 3.0,
    anchor_tolerance_px: float = 15.0,
    anchor_tolerance_nm: float = 2.0,
    sigma_clip: float = DEFAULT_SIGMA_CLIP,
    max_iterations: int = 5,
    min_intensity: int = 0,
    saturation: Optional[float] = None,
    prominence: Optional[float] = None,
    lamp: str = LAMP_NAME,
    wl_source: str = "unknown",
    source_action_uuid: Optional[str] = None,
) -> WavelengthCalibration:
    """Fit pixel-to-wavelength from a lamp exposure and a few known lines.

    Args:
        counts: The lamp exposure, one value per detector column.
        anchors: ``(pixel, wavelength_nm)`` pairs the operator has
            identified by eye -- at least ``degree + 1`` of them, spread
            across the detector. Both halves are approximate and are snapped:
            the pixel to the nearest detected line, the wavelength to the
            nearest catalogue entry.
        degree: Order of the Chebyshev polynomial. Four is the usual choice
            for a grating spectrograph across a full detector.
        catalogue: ``(wavelength_nm, intensity, species)`` triples. Defaults to
            the bundled krypton list, culled to the lamp's range.
        match_tolerance_px: How far a predicted line may sit from a detected
            one and still be called the same line.
        sigma_clip: Residual threshold for rejection, in standard deviations.
        saturation: Count at which the detector saturates. Lines reaching it
            are excluded, because a flat top has no well-defined centre.

    Returns:
        A :class:`WavelengthCalibration`.

    Raises:
        CalibrationFitError: If too few lines survive to constrain the fit,
            leaving the caller to report a failure rather than a bad axis.
    """
    arr = np.asarray(counts, dtype=float)
    n_pixels = int(arr.size)
    domain = [0.0, float(n_pixels - 1)]

    # The seed must be OVER-determined, not merely determined. A degree-N
    # fit through exactly N+1 points interpolates them, so each anchor's
    # centroid error -- a few tenths of a pixel -- is reproduced exactly at
    # the anchors and amplified between them. The seed then predicts lines
    # further from their true pixels than the lines sit from each other, and
    # the matcher confidently pairs peaks with their neighbours.
    #
    # Measured against a representative 430-900 nm solution over 2560 columns
    # with 26 px mean line spacing, fitting degree 4: 2 anchors predict 67 px
    # out, 3 predict 20 px, 4 predict 5.5 px. Running the whole pipeline, 5
    # isolated anchors still left the axis 8.9 nm out and 6 left it 2.9 nm
    # out, while 8 brought it to 0.002 nm. Widening the match window to cover
    # the shortfall does not rescue it either: a window wider than half the
    # line spacing is ambiguous by construction, and a wide first pass
    # measured *worse* than a narrow one because the mis-matches it admitted
    # bent the fit into agreeing with them.
    #
    # `degree + 1 + MIN_EXCESS_LINES` is the same margin this module already
    # requires of the final fit, and for the same reason.
    min_anchors = degree + 1 + MIN_EXCESS_LINES
    if len(anchors) < min_anchors:
        raise CalibrationFitError(
            f"a degree-{degree} fit needs at least {min_anchors} anchors to "
            f"seed it, got {len(anchors)}. Identify more lines, spread across "
            f"the detector, or ask for a lower degree."
        )

    cat = (
        list(catalogue)
        if catalogue is not None
        else usable_catalogue(min_intensity=min_intensity)
    )
    if not cat:
        raise CalibrationFitError("the catalogue is empty after filtering")

    found = detect_peaks(arr, prominence=prominence)
    centroids = centroid_peaks(arr, found, saturation=saturation)
    n_saturated = sum(1 for c in centroids if c.saturated)
    usable = [c for c in centroids if not c.saturated]
    if len(usable) < degree + 1 + MIN_EXCESS_LINES:
        raise CalibrationFitError(
            f"only {len(usable)} usable lines detected "
            f"({n_saturated} saturated, {len(found)} peaks found); a degree-"
            f"{degree} fit needs at least {degree + 1 + MIN_EXCESS_LINES}"
        )

    # Seed: a low-order solution through the anchors alone. Its only job is to
    # predict roughly where each catalogue line falls, so its order is capped
    # by how many anchors there are rather than by `degree`.
    seed_px = np.array(
        [_snap_anchor_pixel(p, usable, anchor_tolerance_px) for p, _ in anchors]
    )
    seed_wl = np.array(
        [_snap_anchor_wavelength(w, cat, anchor_tolerance_nm) for _, w in anchors]
    )
    seed_degree = min(len(anchors) - 1, degree)
    coeffs = _fit_chebyshev(seed_px, seed_wl, seed_degree, domain)

    # Identify outward from the anchors, not all at once. Two anchors give
    # only a straight line, and a grating's dispersion is not straight: across
    # this detector the curvature is several nanometres, tens of pixels, far
    # outside any sane match tolerance. A single global match from that seed
    # mis-identifies nearly every line and the fit never recovers. Growing the
    # accepted span outward -- matching where the solution is currently
    # trustworthy, refitting, then reaching further -- is what IRAF's
    # `identify` does, and it is what lets two anchors be enough.
    anchor_matches = [
        MatchedLine(
            pixel=float(px_a),
            wavelength_nm=float(wl_a),
            intensity=0,
            species="anchor",
        )
        for px_a, wl_a in zip(seed_px, seed_wl)
    ]
    matched: list[MatchedLine] = list(anchor_matches)
    cat_wl = np.array([c[0] for c in cat])
    all_pixels = np.arange(n_pixels, dtype=float)

    for _ in range(max_iterations):
        fit_degree = min(degree, max(1, len(matched) - 1 - MIN_EXCESS_LINES))
        coeffs = _fit_chebyshev(
            np.array([m.pixel for m in matched]),
            np.array([m.wavelength_nm for m in matched]),
            fit_degree,
            domain,
        )
        solution = np.polynomial.chebyshev.Chebyshev(coeffs, domain=domain)
        dispersion = np.abs(np.gradient(solution(all_pixels)))

        candidates = []
        for centroid in usable:
            local_disp = float(dispersion[int(round(centroid.pixel))])
            if local_disp <= 0:
                continue
            wl_guess = float(solution(centroid.pixel))
            j = int(np.argmin(np.abs(cat_wl - wl_guess)))
            if abs(cat_wl[j] - wl_guess) <= match_tolerance_px * local_disp:
                candidates.append(
                    MatchedLine(
                        pixel=centroid.pixel,
                        wavelength_nm=float(cat[j][0]),
                        intensity=int(cat[j][1]),
                        species=str(cat[j][2]),
                    )
                )

        # One catalogue line cannot be two detected lines. When two centroids
        # claim the same entry the closer one keeps it: the other is a blend
        # or a cosmic ray, and letting both through would put two different
        # pixels at one wavelength.
        candidates = _drop_duplicate_identifications(candidates, solution)
        if len(candidates) >= degree + 1:
            matched = candidates

    if len(matched) < degree + 1 + MIN_EXCESS_LINES:
        raise CalibrationFitError(
            f"only {len(matched)} lines could be identified against the "
            f"catalogue; a degree-{degree} fit needs at least "
            f"{degree + 1 + MIN_EXCESS_LINES}. Check the anchors: a wrong one "
            f"seeds a solution that matches nothing."
        )

    # Final solution over everything identified, with the mis-identifications
    # clipped out. Repeated until nothing more is rejected.
    for _ in range(max_iterations):
        coeffs, kept = _fit_with_rejection(
            np.array([m.pixel for m in matched]),
            np.array([m.wavelength_nm for m in matched]),
            degree,
            domain,
            sigma_clip,
        )
        if kept.all():
            break
        matched = [m for m, k in zip(matched, kept) if k]

    px = np.array([m.pixel for m in matched])
    wl = np.array([m.wavelength_nm for m in matched])
    residuals = np.polynomial.chebyshev.Chebyshev(coeffs, domain=domain)(px) - wl
    return WavelengthCalibration(
        model=MODEL_CHEB,
        coeffs=[float(c) for c in coeffs],
        domain=domain,
        n_pixels=n_pixels,
        fit_rms_nm=float(np.sqrt(np.mean(residuals**2))),
        max_residual_nm=float(np.max(np.abs(residuals))) if residuals.size else 0.0,
        n_lines=len(matched),
        n_rejected=len(usable) - len(matched),
        n_saturated=n_saturated,
        medium=MEDIUM,
        lamp=lamp,
        created=_utc_now(),
        wl_source=wl_source,
        source_action_uuid=source_action_uuid,
    )


def _drop_duplicate_identifications(
    matched: Sequence[MatchedLine], solution
) -> list[MatchedLine]:
    """Keep only the best-fitting centroid for each catalogue wavelength."""
    best: dict[float, MatchedLine] = {}
    for m in matched:
        err = abs(float(solution(m.pixel)) - m.wavelength_nm)
        incumbent = best.get(m.wavelength_nm)
        if incumbent is None:
            best[m.wavelength_nm] = m
        else:
            if err < abs(float(solution(incumbent.pixel)) - incumbent.wavelength_nm):
                best[m.wavelength_nm] = m
    return sorted(best.values(), key=lambda m: m.pixel)


def _fit_with_rejection(
    pixels: np.ndarray,
    wavelengths: np.ndarray,
    degree: int,
    domain: list[float],
    sigma_clip: float,
) -> tuple[np.ndarray, np.ndarray]:
    """One clipping pass: fit, then flag lines beyond ``sigma_clip`` sigma.

    Returns the coefficients and a boolean mask of the lines that survived.
    Refuses to clip below the minimum: a solution is not improved by throwing
    away the evidence for it.
    """
    coeffs = _fit_chebyshev(pixels, wavelengths, degree, domain)
    residuals = (
        np.polynomial.chebyshev.Chebyshev(coeffs, domain=domain)(pixels) - wavelengths
    )
    sigma = float(np.std(residuals))
    if sigma <= 0:
        return coeffs, np.ones(pixels.size, dtype=bool)
    keep = np.abs(residuals) <= sigma_clip * sigma
    if keep.sum() < degree + 1 + MIN_EXCESS_LINES:
        return coeffs, np.ones(pixels.size, dtype=bool)
    if keep.all():
        return coeffs, keep
    return _fit_chebyshev(pixels[keep], wavelengths[keep], degree, domain), keep


def fit_from_pairs(
    pairs: Sequence[tuple[float, float]],
    n_pixels: int,
    *,
    degree: int = 2,
    lamp: str = "manual",
    wl_source: str = "unknown",
    source_action_uuid: Optional[str] = None,
) -> WavelengthCalibration:
    """Fit an axis directly from ``(channel, wavelength_nm)`` pairs.

    No peak detection, no catalogue, no identification: the caller has
    already decided which channel is which wavelength, and this only fits
    them. That makes it the right tool when the lines are known by other
    means, and the wrong one when they are not -- nothing here can notice a
    mislabelled pair, because there is no independent evidence to notice it
    against.

    Second order by default. A grating's dispersion is not quadratic, so this
    will not describe a full detector as well as the fourth-order solution
    :func:`fit_wavelength` produces; over a narrow span, or with only a few
    known lines, it is the honest order to ask for.

    Raises:
        CalibrationFitError: With fewer pairs than the degree can support.
    """
    if n_pixels < 2:
        raise CalibrationFitError(f"n_pixels must be at least 2, got {n_pixels}")
    cleaned = [(float(c), float(w)) for c, w in pairs]
    if len(cleaned) < degree + 1:
        raise CalibrationFitError(
            f"a degree-{degree} fit needs at least {degree + 1} pairs, "
            f"got {len(cleaned)}"
        )
    px = np.array([c for c, _w in cleaned])
    wl = np.array([w for _c, w in cleaned])
    if len(set(px.tolist())) != len(px):
        raise CalibrationFitError("two pairs name the same channel")
    domain = [0.0, float(n_pixels - 1)]
    coeffs = _fit_chebyshev(px, wl, degree, domain)
    residuals = np.polynomial.chebyshev.Chebyshev(coeffs, domain=domain)(px) - wl
    return WavelengthCalibration(
        model=MODEL_CHEB,
        coeffs=[float(c) for c in coeffs],
        domain=domain,
        n_pixels=int(n_pixels),
        # Exactly degree+1 pairs interpolate, so this is 0 and means nothing.
        # Reported anyway rather than suppressed: the pair count is beside it.
        fit_rms_nm=float(np.sqrt(np.mean(residuals**2))),
        max_residual_nm=float(np.max(np.abs(residuals))),
        n_lines=len(cleaned),
        n_rejected=0,
        n_saturated=0,
        medium=MEDIUM,
        lamp=lamp,
        created=_utc_now(),
        wl_source=wl_source,
        source_action_uuid=source_action_uuid,
    )
