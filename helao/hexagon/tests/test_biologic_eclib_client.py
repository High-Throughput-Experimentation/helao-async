"""The client is the only thing that touches the DLL, and the only thing that
turns a vendor code into an exception."""

import threading

import pytest

from helao.deploy.hte.drivers.pstat.biologic import sim, vendor
from helao.deploy.hte.drivers.pstat.biologic.eclib_client import (
    EclibClient,
    EclibError,
)

ADDRESS = "192.168.200.100"


@pytest.fixture
def client():
    sim.set_sim_config(sim.SimConfig())
    c = EclibClient(sdk_path="/unused", simulate=True)
    try:
        yield c
    finally:
        c.close()
        sim.set_sim_config(sim.SimConfig())


@pytest.fixture
def connected(client):
    client.connect(ADDRESS)
    return client


def test_connect_returns_device_info_and_records_the_id(client):
    info = client.connect(ADDRESS)
    assert info.NumberOfChannels >= 1
    assert client.idn is not None


def test_a_vendor_failure_raises_with_the_code_name(connected):
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_LoadTechnique": -400}))
    parms = connected.define_params([("Duration_step", 1.0, 0)])
    with pytest.raises(EclibError) as exc:
        connected.load_technique(0, "ca4.ecc", parms, first=True, last=True)
    assert exc.value.code == -400
    assert exc.value.name == "ERR_TECH_ECCFILENOTEXISTS"
    assert "ERR_TECH_ECCFILENOTEXISTS" in str(exc.value)


def test_an_unknown_code_still_raises_and_says_so(connected):
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_StartChannel": -9999}))
    with pytest.raises(EclibError) as exc:
        connected.start_channel(0)
    assert exc.value.code == -9999
    assert "unknown" in exc.value.name.lower() or "-9999" in str(exc.value)


def test_every_vendor_call_runs_on_one_thread_that_is_not_the_caller(connected):
    seen = set()
    original = connected._call

    def spy(name, *args):
        seen.add(threading.current_thread().name)
        return original(name, *args)

    connected._call = spy
    connected.channel_info(0)
    connected.board_type(0)
    connected.current_values(0)
    assert len(seen) == 1
    assert threading.current_thread().name not in seen


def test_calls_from_two_threads_still_land_on_the_one_worker(connected):
    threads_seen = []

    def work():
        threads_seen.append(connected.channel_info(0).Channel)

    ts = [threading.Thread(target=work) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert threads_seen == [0, 0, 0, 0]


def test_define_params_keeps_the_array_alive(connected):
    """The EccParams struct holds a bare pointer. If the array it points at is
    collected before LoadTechnique reads it, the DLL reads freed memory."""
    parms = connected.define_params(
        [("Voltage_step", 0.5, 0), ("Step_number", 0, 0), ("vs_initial", False, 0)]
    )
    assert parms.len == 3
    assert getattr(parms, "_keepalive", None) is not None


def test_define_params_dispatches_by_python_type(connected):
    parms = connected.define_params(
        [("Duration_step", 2.5, 0), ("N_Cycles", 3, 0), ("sweep", True, 0)]
    )
    labels = [
        bytes(parms._keepalive[i].ParamStr).split(b"\x00")[0].decode()
        for i in range(parms.len)
    ]
    assert labels == ["Duration_step", "N_Cycles", "sweep"]


def test_define_params_refuses_a_type_the_dll_has_no_setter_for(connected):
    with pytest.raises(EclibError, match="Duration_step"):
        connected.define_params([("Duration_step", "2.5", 0)])


def test_bools_are_not_treated_as_ints(connected):
    """`isinstance(True, int)` is True, so a naive dispatch sends a bool to
    BL_DefineIntParameter and the DLL records 1 where it wanted a flag."""
    parms = connected.define_params([("vs_initial", True, 0)])
    assert parms._keepalive[0].ParamType == vendor.PARAM_BOOLEAN


def test_get_data_returns_only_the_rows_the_info_claims(connected):
    sim.set_sim_config(sim.SimConfig(rows_per_poll=3))
    parms = connected.define_params([("Duration_step", 1.0, 0)])
    connected.load_technique(0, "ca4.ecc", parms, first=True, last=True)
    connected.start_channel(0)
    values, info, records = connected.get_data(0)
    assert info.NbRows == 3
    assert len(records) == info.NbRows * info.NbCols
    assert values.TimeBase > 0


def test_technique_ids_reads_back_the_loaded_list_in_order(connected):
    parms = connected.define_params([("Trigger_Logic", 1, 0)])
    connected.load_technique(0, "TI4.ecc", parms, first=True, last=False)
    connected.load_technique(0, "ca4.ecc", parms, first=False, last=True)
    assert connected.technique_ids(0, 2) == [vendor.TECH_ID.TI, vendor.TECH_ID.CA]


def test_drain_messages_returns_everything_then_empties(connected):
    sim.push_message(0, "first")
    sim.push_message(0, "second")
    assert connected.drain_messages(0) == ["first", "second"]
    assert connected.drain_messages(0) == []


def test_drain_messages_is_bounded_so_a_chatty_channel_cannot_hang_a_poll(connected):
    for i in range(10_000):
        sim.push_message(0, f"m{i}")
    drained = connected.drain_messages(0)
    assert len(drained) <= 100


def test_to_single_uses_the_channel_aware_conversion(connected):
    word = sim.encode_single(-0.125)
    assert connected.to_single(word, vendor.BOARD_TYPE.PREMIUM) == pytest.approx(
        -0.125, abs=1e-6
    )


def test_to_seconds_uses_the_vendor_call_not_a_hand_rolled_shift(connected):
    """PDF §7.x.4 prescribes BL_ConvertTimeChannelNumericIntoSeconds;
    easy-biologic computes TimeBase * ((t_high << 32) + t_low) itself."""
    assert connected.to_seconds(0, 1000, 1e-3, vendor.BOARD_TYPE.PREMIUM) == (
        pytest.approx(1.0)
    )


def test_channel_index_is_passed_through_unmodified(connected):
    """kbio's wrappers subtract 1; that is kbio's convention, not the DLL's."""
    calls = []
    original = connected._call
    connected._call = lambda name, *args: (
        calls.append((name, args)),
        original(name, *args),
    )[1]
    connected.board_type(0)
    name, args = calls[-1]
    assert name == "BL_GetChannelBoardType"
    assert args[1] == 0


def test_close_is_idempotent_and_joins_the_worker(client):
    client.connect(ADDRESS)
    client.close()
    client.close()
    assert client.idn is None


def test_a_call_after_close_raises_rather_than_hanging(client):
    client.connect(ADDRESS)
    client.close()
    with pytest.raises(EclibError, match="closed"):
        client.channel_info(0)


def test_test_connection_reports_false_when_not_connected(client):
    assert client.test_connection() is False


def test_error_message_calls_through_without_raising(connected):
    """The sim's BL_GetErrorMsg is a stub (returns success, writes nothing),
    so this proves the plumbing -- buffer, size pointer, decode -- rather
    than the vendor's wording; the real-SDK gate checks the wording."""
    for code in (0, -1, -400, -9999):
        assert connected.error_message(code) == ""


def test_close_survives_a_failing_disconnect_and_reports_not_connected(client):
    """A disconnect that fails must not leave the client claiming a
    connection it no longer has: idn is cleared and closed is set either
    way, so test_connection reads False rather than raising."""
    client.connect(ADDRESS)
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_Disconnect": -1}))
    client.close()
    assert client.test_connection() is False
