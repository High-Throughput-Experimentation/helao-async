"""Executing a technique plan against the simulated EC-Lib 2.0 SDK.

These run the whole stack -- plan, enum resolution, parameter setters, download,
reader dispatch, column mapping -- with no DLL and no instrument, which is the
point of :mod:`sim`.
"""

import threading

import pytest

from helao.deploy.hte.drivers.pstat.biologic_eclib2 import data as ec2data
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import sim
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import technique as ec2tech
from helao.deploy.hte.drivers.pstat.biologic_eclib2.sdk_client import (
    Eclib2Error,
    SdkClient,
    open_client,
)
from helao.hexagon.tests.biologic_eclib2_sample_params import params

CHANNEL = 0


@pytest.fixture
def client():
    c = open_client(simulate=True)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def live(client):
    client.connect("192.168.200.100")
    client.load_firmware(CHANNEL)
    return client


def _run_to_completion(client, channel=CHANNEL, limit=200):
    """Start and drain a channel, returning the concatenated table."""
    client.start(channel)
    plan = client.plan_for(channel)
    table = {c: [] for c in plan.columns}
    seen = []
    for _ in range(limit):
        result = client.poll(channel)
        for column, values in result.table.items():
            table[column].extend(values)
        if result.rows:
            seen.append((result.technique_identifier, result.rows))
        if not result.running and result.rows == 0:
            break
    else:
        raise AssertionError("channel never went idle")
    return table, seen


# --------------------------------------------------------------------------
# thread discipline
# --------------------------------------------------------------------------


def test_every_vendor_call_runs_on_one_dedicated_thread(live):
    # The SDK is documented as not thread-safe and its handles cannot be
    # shared across threads. A violation corrupts acquisitions rather than
    # raising, so this is the test that has to hold.
    ids = set()
    ids.add(live.worker_thread_id)
    live.apply_plan(CHANNEL, ec2tech.build_plan("OCV", params("OCV")))
    ids.add(live.worker_thread_id)

    def from_another_thread():
        live.poll(CHANNEL)
        ids.add(live.worker_thread_id)

    live.start(CHANNEL)
    thread = threading.Thread(target=from_another_thread)
    thread.start()
    thread.join()

    assert len(ids) == 1
    assert live.worker_thread_id != threading.get_ident()


def test_the_client_refuses_use_after_close(client):
    client.close()
    with pytest.raises(Eclib2Error, match="client is closed"):
        client.connect("192.168.200.100")


def test_closing_twice_is_harmless(client):
    client.close()
    client.close()


# --------------------------------------------------------------------------
# connection
# --------------------------------------------------------------------------


def test_connect_records_the_device_info(client):
    assert client.connected is False
    info = client.connect("192.168.200.100")
    assert client.connected is True
    # SP-300 is device_code 16, and it is on the SDK's supported list.
    assert info.device_code == 16


def test_calls_before_connecting_say_so(client):
    with pytest.raises(Eclib2Error, match="not connected"):
        client.start(CHANNEL)
    with pytest.raises(Eclib2Error, match="not connected"):
        client.poll(CHANNEL)


def test_disconnect_is_idempotent_and_clears_state(live):
    live.apply_plan(CHANNEL, ec2tech.build_plan("OCV", params("OCV")))
    live.disconnect()
    assert live.connected is False
    assert live.plan_for(CHANNEL) is None
    live.disconnect()


def test_a_failing_disconnect_still_drops_the_connection():
    # Otherwise the client believes it owns a connection it cannot use, and
    # every later call fails against a dead handle instead of reconnecting.
    client = SdkClient(
        sim.sim_modules(fail_on={"BL_Disconnect": sim.ErrorCode.EC_SDK_ERROR_NOERROR}),
        "<simulated>",
    )
    try:
        client.connect("192.168.200.100")
        with pytest.raises(Eclib2Error):
            client.disconnect()
        assert client.connected is False
    finally:
        client.close()


def test_a_channel_whose_firmware_did_not_load_is_reported():
    # BL_LoadFirmware returns per-channel codes rather than raising, so a
    # failed channel is invisible unless checked.
    modules = sim.sim_modules()
    client = SdkClient(modules, "<simulated>")
    try:
        client.connect("192.168.200.100")
        original = client._api.BL_LoadFirmware

        def bad(conn, mask, force):
            original(conn, mask, force)
            return [sim.ErrorCode.EC_SDK_ERROR_LICENSE_NOT_AUTHORISED] * len(mask)

        client._api.BL_LoadFirmware = bad
        with pytest.raises(Eclib2Error, match="did not load firmware"):
            client.load_firmware(CHANNEL)
    finally:
        client.close()


# --------------------------------------------------------------------------
# error translation
# --------------------------------------------------------------------------


def test_a_license_failure_names_the_code_and_the_cause():
    # -99900 on its own is unreadable; the hint is the difference between "the
    # cable is wrong" and "there is no license file".
    client = SdkClient(
        sim.sim_modules(
            fail_on={"BL_Connect": sim.ErrorCode.EC_SDK_ERROR_LICENSE_NOT_VALID}
        ),
        "<simulated>",
    )
    try:
        with pytest.raises(Eclib2Error) as excinfo:
            client.connect("192.168.200.100")
        assert excinfo.value.code_name == "EC_SDK_ERROR_LICENSE_NOT_VALID"
        assert "license_biologic_" in str(excinfo.value)
    finally:
        client.close()


def test_an_eis_license_failure_points_at_the_eis_option():
    client = SdkClient(
        sim.sim_modules(
            fail_on={
                "BL_StartChannel": (
                    sim.ErrorCode.EC_SDK_ERROR_LICENSE_TECHNIQUE_EIS_NOT_AUTHORISED
                )
            }
        ),
        "<simulated>",
    )
    try:
        client.connect("192.168.200.100")
        client.load_firmware(CHANNEL)
        client.apply_plan(CHANNEL, ec2tech.build_plan("PEIS", params("PEIS")))
        with pytest.raises(Eclib2Error, match="EIS option"):
            client.start(CHANNEL)
    finally:
        client.close()


# --------------------------------------------------------------------------
# plan application
# --------------------------------------------------------------------------


def test_applying_a_plan_adds_one_technique_per_plan_entry(live):
    live.apply_plan(CHANNEL, ec2tech.build_plan("PEIS", params("PEIS")))
    added = [c[2].name for c in live._api.calls if c[0] == "BL_AddTechnique"]
    assert added == ["EC_SDK_TECHNIQUE_CA", "EC_SDK_TECHNIQUE_PEIS"]


def test_every_parameter_in_the_plan_reaches_the_instrument(live):
    plan = ec2tech.build_plan("CA", params("CA", IRange="m10", ERange="v5"))
    live.apply_plan(CHANNEL, plan)
    (tech,) = live._api.techniques.values()
    for param in plan.techniques[0].params:
        assert param.name in tech.params, param.name
    assert tech.params["EC_SDK_VOLTAGE_STEP_IN_V"] == [0.5]
    assert tech.params["EC_SDK_STEP_NUMBER"] == 0
    assert tech.params["EC_SDK_RECORD_EVERY_DT_ARRAY_MODE"] is False


def test_enum_parameters_are_resolved_to_vendor_members_not_left_as_strings(live):
    live.apply_plan(CHANNEL, ec2tech.build_plan("PEIS", params("PEIS")))
    peis = [
        t
        for t in live._api.techniques.values()
        if t.identifier.name == "EC_SDK_TECHNIQUE_PEIS"
    ][0]
    assert peis.params["EC_SDK_SWEEP_MODE"] is sim.SweepMode.EC_SDK_SWEEP_LOG
    ca = [
        t
        for t in live._api.techniques.values()
        if t.identifier.name == "EC_SDK_TECHNIQUE_CA"
    ][0]
    assert ca.params["EC_SDK_VS_INITIAL"] == [sim.VsInitial.EC_SDK_VS_EREF]


def test_ranges_are_set_per_technique_handle(live):
    live.apply_plan(
        CHANNEL, ec2tech.build_plan("PEIS", params("PEIS", IRange="AUTO", ERange="v10"))
    )
    for tech in live._api.techniques.values():
        assert tech.irange == (
            sim.IRangeMode.I_RANGE_MODE_AUTO,
            sim.IRangeValue.EC_SDK_IRANGE_1mA,
        )
        assert tech.erange is sim.ERangeValue.EC_SDK_ERANGE_10


def test_ranges_are_left_alone_when_the_plan_omits_them(live):
    live.apply_plan(CHANNEL, ec2tech.build_plan("CA", params("CA")))
    (tech,) = live._api.techniques.values()
    assert tech.irange is None
    assert tech.erange is None
    assert tech.bandwidth is None


def test_reapplying_a_plan_deletes_the_previous_experiment(live):
    live.apply_plan(CHANNEL, ec2tech.build_plan("OCV", params("OCV")))
    live.apply_plan(CHANNEL, ec2tech.build_plan("CA", params("CA")))
    deleted = [c for c in live._api.calls if c[0] == "BL_DeleteExperiment"]
    assert len(deleted) == 1
    # Only the new plan is loaded.
    assert live.plan_for(CHANNEL).technique_name == "CA"


def test_a_half_built_experiment_is_deleted_rather_than_left_loadable(live):
    # A leftover experiment would be picked up by the next start and run
    # something nobody asked for.
    original = live._api.BL_SetFloatParameter

    def boom(*a, **k):
        raise sim.EC_SDK_Runtime_Error("no", sim.ErrorCode.EC_SDK_ERROR_NOERROR)

    live._api.BL_SetFloatParameter = boom
    try:
        with pytest.raises(Eclib2Error):
            live.apply_plan(CHANNEL, ec2tech.build_plan("OCV", params("OCV")))
    finally:
        live._api.BL_SetFloatParameter = original
    assert live.plan_for(CHANNEL) is None
    assert any(c[0] == "BL_DeleteExperiment" for c in live._api.calls)
    assert live._api.experiments == {}


def test_starting_without_a_plan_is_refused(live):
    with pytest.raises(Eclib2Error, match="no plan loaded"):
        live.start(CHANNEL)


# --------------------------------------------------------------------------
# running and reading
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,columns",
    [
        ("OCV", ec2data.OCV_COLUMNS),
        ("CA", ec2data.STEP_COLUMNS),
        ("CP", ec2data.STEP_COLUMNS),
        ("CV", ec2data.STEP_COLUMNS),
        ("PEIS", ec2data.EIS_COLUMNS),
        ("GEIS", ec2data.EIS_COLUMNS),
        ("CAOCV", ec2data.STEP_COLUMNS),
    ],
)
def test_every_technique_runs_and_emits_its_contract_columns(live, name, columns):
    live.apply_plan(CHANNEL, ec2tech.build_plan(name, params(name)))
    table, seen = _run_to_completion(live)
    assert set(table) == set(columns)
    lengths = {len(v) for v in table.values()}
    assert len(lengths) == 1, "columns must stay the same length"
    assert lengths.pop() > 0
    assert seen, "no rows were produced"


def test_the_right_reader_is_chosen_per_technique(live):
    # The simulator raises if BL_ProcessRawTo*Data is called for a technique it
    # does not serve, so a mis-dispatch fails here rather than silently
    # producing garbage columns at the station.
    live.apply_plan(CHANNEL, ec2tech.build_plan("PEIS", params("PEIS")))
    _run_to_completion(live)
    used = [c[0] for c in live._api.calls if c[0].startswith("BL_ProcessRawTo")]
    assert "BL_ProcessRawToCaData" in used
    assert "BL_ProcessRawToEisData" in used


def test_a_composite_emits_both_legs_in_one_table_with_a_process_flag(live):
    live.apply_plan(CHANNEL, ec2tech.build_plan("PEIS", params("PEIS")))
    table, seen = _run_to_completion(live)
    # CA rows first, then the sweep -- the order the techniques were added.
    assert [name for name, _ in seen][0] == "EC_SDK_TECHNIQUE_CA"
    assert [name for name, _ in seen][-1] == "EC_SDK_TECHNIQUE_PEIS"
    assert set(table["process"]) == {0, 1}
    # The frequency column is real only on the sweep rows.
    freqs = [f for f, p in zip(table["f_Hz"], table["process"]) if p == 1]
    assert all(f > 0 for f in freqs)


def test_caocv_pads_the_ocv_leg_into_the_step_columns(live):
    import math

    live.apply_plan(CHANNEL, ec2tech.build_plan("CAOCV", params("CAOCV")))
    table, seen = _run_to_completion(live)
    assert [name for name, _ in seen][-1] == "EC_SDK_TECHNIQUE_OCV"
    # OCV reports no current, so its rows carry NaN there rather than a zero
    # that would read as a real measurement.
    assert any(math.isnan(v) for v in table["I_A"])
    assert not all(math.isnan(v) for v in table["I_A"])


def test_a_poll_with_no_rows_yet_is_not_an_error(live):
    live.apply_plan(CHANNEL, ec2tech.build_plan("OCV", params("OCV")))
    live.start(CHANNEL)
    # Drain, then poll past the end: still a valid result, just empty.
    for _ in range(50):
        if not live.poll(CHANNEL).running:
            break
    result = live.poll(CHANNEL)
    assert result.rows == 0
    assert result.running is False
    assert result.table == {c: [] for c in ec2data.OCV_COLUMNS}


def test_is_running_is_judged_by_enum_name_not_by_integer(live):
    # The two shipped vendor examples disagree on the polarity of
    # channel_state; only the enum is authoritative.
    live.apply_plan(CHANNEL, ec2tech.build_plan("OCV", params("OCV")))
    assert live.is_running(CHANNEL) is False
    live.start(CHANNEL)
    assert live.is_running(CHANNEL) is True
    live.stop(CHANNEL)
    assert live.is_running(CHANNEL) is False


def test_stopping_ends_the_acquisition(live):
    live.apply_plan(CHANNEL, ec2tech.build_plan("CAOCV", params("CAOCV")))
    live.start(CHANNEL)
    live.poll(CHANNEL)
    live.stop(CHANNEL)
    result = live.poll(CHANNEL)
    assert result.running is False


def test_polling_without_a_plan_is_refused(live):
    with pytest.raises(Eclib2Error, match="no plan loaded"):
        live.poll(CHANNEL)


def test_open_client_requires_an_sdk_path_when_not_simulating():
    with pytest.raises(ValueError, match="sdk_path is required"):
        open_client(simulate=False)
