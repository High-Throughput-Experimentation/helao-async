# helao/ui/shared/composition/ternary.py
"""Barycentric-to-cartesian for the ternary diagram.

xy 0.0.5 ships no ternary mark, so the diagram is a scatter in a transformed
plane plus three line segments for the edges. Keeping the transform here, away
from any xy import, is what makes it testable with plain arrays.
"""

from __future__ import annotations

import math

import numpy as np

#: The unit triangle, apex at the top: first component bottom-left, second
#: bottom-right, third at the apex.
VERTICES = ((0.0, 0.0), (1.0, 0.0), (0.5, math.sqrt(3) / 2))


def barycentric_to_cartesian(a, b, c) -> tuple:
    """Project three components onto the unit triangle.

    The triple is normalised to sum to 1 per point, which is what lets any unit
    be plotted here and not only ``atomic_fraction``: raw nanomoles carry a
    magnitude a ternary diagram has no axis for.

    A point is dropped when any component is non-finite (an uncalibrated
    transition arrives as ``None`` and becomes NaN), when any component is
    negative (a negative fit residual is not a composition), or when the three
    sum to zero (no direction to project).

    Args:
        a: First component, one value per point.
        b: Second component.
        c: Third component.

    Returns:
        tuple: ``(xs, ys, keep)``. ``xs``/``ys`` hold only the kept points;
        ``keep`` is a boolean mask over the *input*, so a caller can filter its
        own parallel arrays with it.

    Raises:
        ValueError: If the three inputs differ in length.
    """
    arrays = [np.asarray(v, dtype=float).ravel() for v in (a, b, c)]
    if len({arr.size for arr in arrays}) != 1:
        raise ValueError(
            "a, b and c must be the same length, got "
            f"{[int(arr.size) for arr in arrays]}"
        )
    stacked = np.vstack(arrays)
    totals = stacked.sum(axis=0)
    keep = (
        np.isfinite(stacked).all(axis=0)
        & (stacked >= 0).all(axis=0)
        & np.isfinite(totals)
        & (totals > 0)
    )
    if not keep.any():
        return np.array([]), np.array([]), keep
    kept = stacked[:, keep] / totals[keep]
    xs = kept[0] * VERTICES[0][0] + kept[1] * VERTICES[1][0] + kept[2] * VERTICES[2][0]
    ys = kept[0] * VERTICES[0][1] + kept[1] * VERTICES[1][1] + kept[2] * VERTICES[2][1]
    return xs, ys, keep


def triangle_edges() -> tuple:
    """The triangle outline as one closed polyline: ``(xs, ys)``, 4 points."""
    xs = np.array([v[0] for v in VERTICES] + [VERTICES[0][0]], dtype=float)
    ys = np.array([v[1] for v in VERTICES] + [VERTICES[0][1]], dtype=float)
    return xs, ys
