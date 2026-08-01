"""Unit tests for the Reflex UI stack's numeric ring buffer and row buffer."""

import numpy as np
import pytest

from helao.core.servers.reflex.ringbuffer import RingBuffer, RowBuffer


def test_append_then_snapshot_returns_what_went_in():
    buf = RingBuffer(["epoch", "value"], capacity=10)
    buf.append({"epoch": [1.0, 2.0], "value": [10.0, 20.0]})
    snap = buf.snapshot()
    assert list(snap.keys()) == ["epoch", "value"]
    np.testing.assert_allclose(snap["epoch"], [1.0, 2.0])
    np.testing.assert_allclose(snap["value"], [10.0, 20.0])
    assert buf.length == 2


def test_rollover_drops_oldest_rows():
    buf = RingBuffer(["v"], capacity=3)
    buf.append({"v": [1.0, 2.0, 3.0, 4.0, 5.0]})
    snap = buf.snapshot()
    np.testing.assert_allclose(snap["v"], [3.0, 4.0, 5.0])
    assert buf.length == 3


def test_snapshot_n_returns_only_the_last_n_rows():
    buf = RingBuffer(["v"], capacity=100)
    buf.append({"v": list(range(10))})
    np.testing.assert_allclose(buf.snapshot(3)["v"], [7.0, 8.0, 9.0])


def test_snapshot_n_larger_than_length_returns_everything():
    buf = RingBuffer(["v"], capacity=100)
    buf.append({"v": [1.0, 2.0]})
    np.testing.assert_allclose(buf.snapshot(50)["v"], [1.0, 2.0])


def test_new_column_backfills_existing_rows_with_nan():
    buf = RingBuffer(["a"], capacity=10)
    buf.append({"a": [1.0, 2.0]})
    buf.append({"a": [3.0], "b": [30.0]})
    snap = buf.snapshot()
    np.testing.assert_allclose(snap["a"], [1.0, 2.0, 3.0])
    assert np.isnan(snap["b"][0]) and np.isnan(snap["b"][1])
    np.testing.assert_allclose(snap["b"][2:], [30.0])


def test_missing_column_in_append_fills_nan():
    buf = RingBuffer(["a", "b"], capacity=10)
    buf.append({"a": [1.0]})
    snap = buf.snapshot()
    np.testing.assert_allclose(snap["a"], [1.0])
    assert np.isnan(snap["b"][0])


def test_incremental_appends_wrap_and_keep_the_newest_rows():
    """The split-write path: no single append exceeds capacity here."""
    buf = RingBuffer(["v"], capacity=3)
    buf.append({"v": [1.0, 2.0]})
    buf.append({"v": [3.0, 4.0]})
    np.testing.assert_allclose(buf.snapshot()["v"], [2.0, 3.0, 4.0])


def test_snapshot_window_spanning_the_wrap_point():
    buf = RingBuffer(["v"], capacity=3)
    buf.append({"v": [1.0, 2.0]})
    buf.append({"v": [3.0, 4.0]})
    np.testing.assert_allclose(buf.snapshot(2)["v"], [3.0, 4.0])


def test_repeated_small_appends_wrapping_more_than_once():
    buf = RingBuffer(["v"], capacity=3)
    for i in range(10):
        buf.append({"v": [float(i)]})
    np.testing.assert_allclose(buf.snapshot()["v"], [7.0, 8.0, 9.0])
    assert buf.length == 3


def test_multi_column_stays_aligned_across_a_wrap():
    buf = RingBuffer(["a", "b"], capacity=3)
    buf.append({"a": [1.0, 2.0], "b": [10.0, 20.0]})
    buf.append({"a": [3.0, 4.0], "b": [30.0, 40.0]})
    snap = buf.snapshot()
    np.testing.assert_allclose(snap["a"], [2.0, 3.0, 4.0])
    np.testing.assert_allclose(snap["b"], [20.0, 30.0, 40.0])


def test_column_added_after_a_wrap_aligns_with_existing_rows():
    buf = RingBuffer(["a"], capacity=3)
    buf.append({"a": [1.0, 2.0]})
    buf.append({"a": [3.0, 4.0]})  # now wrapped, _start != 0
    buf.append({"a": [5.0], "b": [50.0]})
    snap = buf.snapshot()
    np.testing.assert_allclose(snap["a"], [3.0, 4.0, 5.0])
    assert np.isnan(snap["b"][0]) and np.isnan(snap["b"][1])
    np.testing.assert_allclose(snap["b"][2:], [50.0])


def test_a_rejected_append_leaves_the_column_set_untouched():
    """Validation precedes mutation: no phantom column from a failed append."""
    buf = RingBuffer(["v"], capacity=5)
    with pytest.raises(ValueError):
        buf.append({"v": [1.0], "bad": ["not a number"]})
    assert buf.columns == ["v"]
    assert buf.length == 0


def test_a_rejected_ragged_append_leaves_the_column_set_untouched():
    buf = RingBuffer(["v"], capacity=5)
    with pytest.raises(ValueError):
        buf.append({"v": [1.0, 2.0], "other": [1.0]})
    assert buf.columns == ["v"]
    assert buf.length == 0


def test_rowbuffer_returns_copies_so_callers_cannot_corrupt_it():
    rows = RowBuffer(maxlen=2)
    rows.append({"i": 1})
    rows.rows()[0]["i"] = 999
    rows.latest()["i"] = 999  # type: ignore[index]
    assert rows.rows() == [{"i": 1}]


def test_ragged_append_raises():
    buf = RingBuffer(["a", "b"], capacity=10)
    with pytest.raises(ValueError):
        buf.append({"a": [1.0, 2.0], "b": [1.0]})


def test_append_longer_than_capacity_keeps_the_tail():
    buf = RingBuffer(["v"], capacity=3)
    buf.append({"v": list(range(100))})
    np.testing.assert_allclose(buf.snapshot()["v"], [97.0, 98.0, 99.0])


def test_empty_snapshot_returns_empty_arrays_not_none():
    buf = RingBuffer(["v"], capacity=10)
    snap = buf.snapshot()
    assert snap["v"].shape == (0,)


def test_clear_resets_length_but_keeps_columns():
    buf = RingBuffer(["v"], capacity=10)
    buf.append({"v": [1.0]})
    buf.clear()
    assert buf.length == 0
    assert buf.columns == ["v"]


def test_non_numeric_value_raises():
    buf = RingBuffer(["v"], capacity=10)
    with pytest.raises((ValueError, TypeError)):
        buf.append({"v": ["not a number"]})


def test_rowbuffer_keeps_last_maxlen_rows_in_order():
    rows = RowBuffer(maxlen=2)
    rows.append({"i": 1})
    rows.append({"i": 2})
    rows.append({"i": 3})
    assert rows.rows() == [{"i": 2}, {"i": 3}]
    assert rows.latest() == {"i": 3}
    assert len(rows) == 2


def test_rowbuffer_latest_is_none_when_empty():
    assert RowBuffer().latest() is None
