# helao/ui/shared/composition/interp.py
"""Interpolate measured values across every platemap position.

The plate-map toggle's whole point is to show more points than were measured,
so the surface is evaluated at the platemap's positions rather than on a grid.
"""

from __future__ import annotations

import numpy as np

#: Below this many distinct measured points there is no surface to fit, and the
#: toggle reports that rather than drawing one.
MIN_POINTS = 4


def rbf_surface(
    xs,
    ys,
    values,
    target_xs,
    target_ys,
    *,
    kernel: str = "thin_plate_spline",
) -> np.ndarray:
    """Fit an RBF to the measured points and evaluate it at the targets.

    Two guards, both for failures `RBFInterpolator` reports as an exception
    from inside a render:

    * Points whose coordinate or value is non-finite are dropped first. An
      uncalibrated transition arrives as ``None`` and becomes NaN.
    * Duplicated coordinates are collapsed to their mean. Two measurements of
      one position is normal here -- a pre-anneal and a post-anneal process sit
      on the same sample -- and a repeated coordinate makes the system singular.

    Args:
        xs: Measured x coordinates.
        ys: Measured y coordinates.
        values: Measured values, one per point.
        target_xs: Positions to evaluate at.
        target_ys: Positions to evaluate at.
        kernel: An `RBFInterpolator` kernel name.

    Returns:
        numpy.ndarray: One value per target, or an empty array when there are
        fewer than :data:`MIN_POINTS` usable points or no targets.

    Raises:
        ValueError: If ``xs``, ``ys`` and ``values`` differ in length, or if the
            two target arrays differ in length.
    """
    px = np.asarray(xs, dtype=float).ravel()
    py = np.asarray(ys, dtype=float).ravel()
    pv = np.asarray(values, dtype=float).ravel()
    if not (px.size == py.size == pv.size):
        raise ValueError(
            f"xs, ys and values must be the same length, got "
            f"{int(px.size)}, {int(py.size)}, {int(pv.size)}"
        )
    tx = np.asarray(target_xs, dtype=float).ravel()
    ty = np.asarray(target_ys, dtype=float).ravel()
    if tx.size != ty.size:
        raise ValueError(
            f"target_xs and target_ys must be the same length, got "
            f"{int(tx.size)}, {int(ty.size)}"
        )
    if tx.size == 0:
        return np.array([])

    keep = np.isfinite(px) & np.isfinite(py) & np.isfinite(pv)
    px, py, pv = px[keep], py[keep], pv[keep]
    if px.size == 0:
        return np.array([])

    points = np.column_stack([px, py])
    unique, inverse = np.unique(points, axis=0, return_inverse=True)
    if unique.shape[0] != points.shape[0]:
        summed = np.zeros(unique.shape[0], dtype=float)
        counts = np.zeros(unique.shape[0], dtype=float)
        np.add.at(summed, inverse, pv)
        np.add.at(counts, inverse, 1.0)
        pv = summed / counts
        points = unique

    if points.shape[0] < MIN_POINTS:
        return np.array([])

    from scipy.interpolate import RBFInterpolator

    interpolator = RBFInterpolator(points, pv, kernel=kernel)
    return np.asarray(interpolator(np.column_stack([tx, ty])), dtype=float)
