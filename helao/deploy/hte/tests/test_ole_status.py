"""Decoding EC-Lab's 32-real MeasureStatus array.

Index meanings are from the EC-Lab OLE COM User Manual v11.72 section 5.2.11.
The one judgement call encoded here: idle is *exactly* index 0 == 0. Every
other value -- including a value this table has never seen -- reads as busy,
because a future EC-Lab adding a state must not make a running channel look
finished.
"""

import pytest

from helao.deploy.hte.drivers.pstat.biologic_ole.status import (
    ChannelState,
    SafetyLimit,
    decode_status,
)


def _arr(**overrides) -> list[float]:
    """A 32-long all-zero status array with named indices overridden."""
    values = [0.0] * 32
    for idx, value in overrides.items():
        values[int(idx.removeprefix("i"))] = float(value)
    return values


def test_a_stopped_channel_is_not_busy():
    status = decode_status(_arr(i0=0))
    assert status.state is ChannelState.STOP
    assert status.is_busy is False


@pytest.mark.parametrize("state_value", [1, 2, 3, 4, 5, 6])
def test_every_non_stop_state_is_busy(state_value):
    status = decode_status(_arr(i0=state_value))
    assert status.is_busy is True


def test_stop_rec_states_are_flagged_as_the_recording_tail():
    """4 and 5 mean 'the last points are being recorded', not 'stopped'."""
    assert decode_status(_arr(i0=4)).is_recording_tail is True
    assert decode_status(_arr(i0=5)).is_recording_tail is True
    assert decode_status(_arr(i0=1)).is_recording_tail is False
    assert decode_status(_arr(i0=0)).is_recording_tail is False


def test_an_unknown_state_is_busy_and_keeps_its_raw_value():
    status = decode_status(_arr(i0=99))
    assert status.state is None
    assert status.state_raw == 99
    assert status.is_busy is True


def test_scalar_fields_land_on_their_documented_indices():
    status = decode_status(
        _arr(
            i4=3,
            i5=54,
            i6=2,
            i10=7,
            i15=1.5,
            i16=0.25,
            i17=-0.1,
            i18=0.4,
            i19=1e-3,
            i23=0.01,
            i25=1000.0,
            i26=52.5,
            i27=11,
            i28=38,
            i29=21.0,
        )
    )
    assert status.technique_index == 3
    assert status.technique_code == 54
    assert status.sequence_index == 2
    assert status.cycle == 7
    assert status.time_s == 1.5
    assert status.ewe_v == 0.25
    assert status.ece_v == -0.1
    assert status.eoc_v == 0.4
    assert status.i_a == 1e-3
    assert status.irange_a == 0.01
    assert status.frequency_hz == 1000.0
    assert status.z_ohm == 52.5
    assert status.point_index == 11
    assert status.total_point_index == 38


def test_safety_limit_decodes_and_zero_means_ok():
    assert decode_status(_arr(i30=0)).safety_limit is SafetyLimit.OK
    assert decode_status(_arr(i30=1)).safety_limit is SafetyLimit.EMAX
    assert decode_status(_arr(i30=9)).safety_limit is SafetyLimit.EWE_MAX_STACK


def test_an_unknown_safety_limit_keeps_its_raw_value():
    status = decode_status(_arr(i30=42))
    assert status.safety_limit is None
    assert status.safety_limit_raw == 42


def test_connection_index_is_inverted_because_zero_means_ok():
    assert decode_status(_arr(i31=0)).connected is True
    assert decode_status(_arr(i31=1)).connected is False


def test_a_wrong_length_array_is_refused():
    with pytest.raises(ValueError, match="32"):
        decode_status([0.0] * 31)


def test_the_raw_array_is_preserved_verbatim():
    values = _arr(i0=1, i15=3.25)
    assert decode_status(values).raw == tuple(values)
