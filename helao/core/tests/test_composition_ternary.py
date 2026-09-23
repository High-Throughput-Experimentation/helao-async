"""Barycentric-to-cartesian for the ternary diagram."""

import math

import pytest

from helao.ui.shared.composition import ternary


def test_a_pure_first_component_lands_on_the_first_vertex() -> None:
    xs, ys, keep = ternary.barycentric_to_cartesian([1.0], [0.0], [0.0])
    assert keep.tolist() == [True]
    assert xs[0] == pytest.approx(ternary.VERTICES[0][0])
    assert ys[0] == pytest.approx(ternary.VERTICES[0][1])


def test_a_pure_third_component_lands_on_the_apex() -> None:
    xs, ys, _ = ternary.barycentric_to_cartesian([0.0], [0.0], [1.0])
    assert xs[0] == pytest.approx(0.5)
    assert ys[0] == pytest.approx(math.sqrt(3) / 2)


def test_an_equal_mixture_lands_at_the_centroid() -> None:
    xs, ys, _ = ternary.barycentric_to_cartesian([1.0], [1.0], [1.0])
    assert xs[0] == pytest.approx(0.5)
    assert ys[0] == pytest.approx(math.sqrt(3) / 6)


def test_an_unnormalised_triple_is_normalised() -> None:
    """Raw nanomoles do not sum to 1. Normalising is what makes any unit
    plottable on a ternary diagram, not just atomic fractions."""
    one = ternary.barycentric_to_cartesian([2.0], [2.0], [2.0])
    two = ternary.barycentric_to_cartesian([1.0], [1.0], [1.0])
    assert one[0][0] == pytest.approx(two[0][0])
    assert one[1][0] == pytest.approx(two[1][0])


def test_a_zero_sum_point_is_dropped() -> None:
    _, _, keep = ternary.barycentric_to_cartesian([0.0], [0.0], [0.0])
    assert keep.tolist() == [False]


def test_a_nan_point_is_dropped() -> None:
    """An uncalibrated transition arrives as None and becomes NaN. Plotting it
    reaches the renderer as a coordinate and blanks the chart."""
    _, _, keep = ternary.barycentric_to_cartesian(
        [1.0, float("nan")], [1.0, 1.0], [1.0, 1.0]
    )
    assert keep.tolist() == [True, False]


def test_a_negative_component_is_dropped() -> None:
    """A negative fit residual is not a composition."""
    _, _, keep = ternary.barycentric_to_cartesian([-1.0], [1.0], [1.0])
    assert keep.tolist() == [False]


def test_dropped_points_are_removed_from_the_outputs() -> None:
    xs, ys, keep = ternary.barycentric_to_cartesian([1.0, 0.0], [0.0, 0.0], [0.0, 0.0])
    assert len(xs) == len(ys) == 1
    assert keep.tolist() == [True, False]


def test_mismatched_lengths_raise() -> None:
    """A caller bug, not something to paper over by truncating."""
    with pytest.raises(ValueError):
        ternary.barycentric_to_cartesian([1.0, 1.0], [1.0], [1.0])


def test_triangle_edges_close_the_triangle() -> None:
    xs, ys = ternary.triangle_edges()
    assert len(xs) == len(ys) == 4
    assert (xs[0], ys[0]) == (xs[-1], ys[-1])
