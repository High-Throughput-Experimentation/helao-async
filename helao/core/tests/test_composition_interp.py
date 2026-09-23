# helao/core/tests/test_composition_interp.py
"""The RBF surface behind the plate-map toggle."""

import pytest

from helao.ui.shared.composition import interp

GRID_X = [0.0, 1.0, 0.0, 1.0, 0.5]
GRID_Y = [0.0, 0.0, 1.0, 1.0, 0.5]


def test_a_plane_is_reproduced_at_an_unmeasured_position() -> None:
    """value = 2x + 3y. An RBF fit on a plane must return the plane."""
    values = [2 * x + 3 * y for x, y in zip(GRID_X, GRID_Y)]
    out = interp.rbf_surface(GRID_X, GRID_Y, values, [0.25], [0.75])
    assert out[0] == pytest.approx(2 * 0.25 + 3 * 0.75, abs=1e-6)


def test_measured_positions_come_back_unchanged() -> None:
    values = [2 * x + 3 * y for x, y in zip(GRID_X, GRID_Y)]
    out = interp.rbf_surface(GRID_X, GRID_Y, values, GRID_X, GRID_Y)
    assert out == pytest.approx(values, abs=1e-6)


def test_too_few_points_returns_empty() -> None:
    """Three points cannot support a surface, and the toggle says so rather
    than drawing one."""
    out = interp.rbf_surface(
        [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 2.0, 3.0], [0.5], [0.5]
    )
    assert out.size == 0


def test_duplicate_coordinates_are_collapsed_not_raised() -> None:
    """RBFInterpolator raises on a singular matrix. Two measurements of one
    position is normal -- pre_anneal and post_anneal sit on the same sample."""
    xs = GRID_X + [0.0]
    ys = GRID_Y + [0.0]
    values = [2 * x + 3 * y for x, y in zip(GRID_X, GRID_Y)] + [10.0]
    out = interp.rbf_surface(xs, ys, values, [0.0], [0.0])
    assert out.size == 1
    assert out[0] == pytest.approx(5.0, abs=1e-6)


def test_non_finite_measurements_are_dropped_before_fitting() -> None:
    xs = GRID_X + [2.0]
    ys = GRID_Y + [2.0]
    values = [2 * x + 3 * y for x, y in zip(GRID_X, GRID_Y)] + [float("nan")]
    out = interp.rbf_surface(xs, ys, values, [0.25], [0.75])
    assert out[0] == pytest.approx(2 * 0.25 + 3 * 0.75, abs=1e-6)


def test_dropping_non_finite_can_fall_below_the_minimum() -> None:
    xs = [0.0, 1.0, 0.0, 1.0]
    ys = [0.0, 0.0, 1.0, 1.0]
    values = [1.0, float("nan"), float("nan"), 2.0]
    assert interp.rbf_surface(xs, ys, values, [0.5], [0.5]).size == 0


def test_no_targets_returns_empty() -> None:
    values = [2 * x + 3 * y for x, y in zip(GRID_X, GRID_Y)]
    assert interp.rbf_surface(GRID_X, GRID_Y, values, [], []).size == 0


def test_mismatched_input_lengths_raise() -> None:
    with pytest.raises(ValueError):
        interp.rbf_surface([0.0, 1.0], [0.0], [1.0, 2.0], [0.5], [0.5])
