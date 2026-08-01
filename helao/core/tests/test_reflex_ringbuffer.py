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
