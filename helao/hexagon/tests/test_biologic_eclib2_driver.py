"""``BiologicEclib2Driver`` against the simulated SDK.

Covers the ``HelaoDriver`` contract, the response shapes the EClib1 backend
publishes, and the column-contract parity that makes this a drop-in.
"""

import asyncio
import math

import pytest

from helao.core.drivers.helao_driver import (
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import data as ec2data
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import technique as ec2tech
from helao.deploy.hte.drivers.pstat.biologic_eclib2.driver import (
    MAX_DRAINS_PER_CALL,
    NOT_PLUGGED,
    BiologicEclib2Driver,
)
from helao.hexagon.tests.biologic_eclib2_sample_params import params

CHANNEL = 0


@pytest.fixture
def driver():
    d = BiologicEclib2Driver(
        {"address": "192.168.200.100", "num_channels": 2, "simulate": True}
    )
    try:
        yield d
    finally:
        d.shutdown()


@pytest.fixture
def connected(driver):
    assert driver.connect().response == DriverResponseType.success
    return driver


async def _run(driver, technique_name, channel=CHANNEL, limit=200):
    """Set up, start, and drain a technique; return the combined table."""
    assert (
        driver.setup(
            technique_name, channel=channel, action_params=params(technique_name)
        ).response
        == DriverResponseType.success
    )
    assert driver.start_channel(channel).response == DriverResponseType.success
    plan_columns = driver.emitted_columns(technique_name)
    table = {c: [] for c in plan_columns}
    for _ in range(limit):
        response = await driver.get_data(channel)
        assert response.response == DriverResponseType.success, response.message
        for column, values in response.data.items():
            table[column].extend(values)
        if response.message == "done":
            return table, response
    raise AssertionError("acquisition never reported done")


# --------------------------------------------------------------------------
# contract and construction
# --------------------------------------------------------------------------


def test_it_is_a_helao_driver():
    assert issubclass(BiologicEclib2Driver, HelaoDriver)


def test_construction_performs_no_device_io():
    # The action server calls connect() at startup. Connecting in __init__
    # would make a construction failure indistinguishable from a config error
    # -- the same reason the EClib1 backend was changed.
    driver = BiologicEclib2Driver({"address": "10.0.0.1", "simulate": True})
    try:
        assert driver.ready is False
        assert driver._client is None
    finally:
        driver.shutdown()


def test_it_constructs_without_the_sdk_or_a_path():
    # This module is in the import graph of a Linux action server.
    driver = BiologicEclib2Driver({})
    try:
        assert driver.ready is False
    finally:
        driver.shutdown()


def test_status_before_connecting_is_uninitialized(driver):
    response = driver.get_status()
    assert response.status == DriverStatus.uninitialized
    assert response.data == {}


def test_connect_reports_the_device_and_marks_ready(connected):
    assert connected.ready is True
    response = connected.get_status()
    assert response.status == DriverStatus.ok
    # Both configured channels are reported. Channel 0 by ChannelState member
    # name; channel 1 is configured but has no board in the simulated SP-300.
    assert set(response.data) == {0, 1}
    assert response.data[0] == "EC_SDK_CHANNEL_STATE_IDLE"
    assert response.data[1] == NOT_PLUGGED


def test_connect_uses_the_instruments_own_account_of_which_channels_exist(connected):
    # The simulated SP-300 has a board in slot 0 only. A configured channel
    # with no board must not fail the connection -- one empty slot would take
    # the whole server down.
    assert connected.plugged_channels == [0]
    assert connected.usable_channels == [0]
    assert connected.missing_channels == [1]


def test_connect_loads_firmware_only_on_channels_that_exist(connected):
    assert connected._client._api.firmware_loaded == [0]
    loads = [c for c in connected._client._api.calls if c[0] == "BL_LoadFirmware"]
    assert len(loads) == 1


def test_connect_reports_missing_channels_rather_than_hiding_them(connected):
    # Silence here would leave a station debugging failing actions with no
    # indication that the channel simply is not there.
    response = connected.connect()
    assert response.data["usable_channels"] == [0]
    assert response.data["missing_channels"] == [1]


def test_connect_fails_when_no_configured_channel_is_plugged():
    driver = BiologicEclib2Driver(
        {"address": "192.168.200.100", "num_channels": 1, "simulate": True}
    )
    try:
        driver.connect()
        # Force the simulated instrument to report an empty chassis.
        driver._client._api.BL_Connect = lambda address, timeout=5: (
            1,
            type(
                "Info",
                (),
                {
                    "device_code": 16,
                    "serial_number": 1,
                    "channels_plugged": [False] * 16,
                },
            )(),
        )
        driver.ready = False
        response = driver.connect()
        assert response.response == DriverResponseType.failed
        assert "are plugged" in response.message
        assert driver.ready is False
    finally:
        driver.shutdown()


def test_an_unplugged_channel_is_refused_with_its_own_message(connected):
    # "not in the config" and "configured but no board fitted" need different
    # fixes, so they must not share a message.
    response = connected.setup("OCV", channel=1, action_params=params("OCV"))
    assert response.response == DriverResponseType.failed
    assert "not plugged" in response.message


def test_an_unplugged_channel_can_still_be_cleaned_up(connected):
    # Otherwise per-channel state set before connecting could never be cleared.
    assert connected.cleanup(1).response == DriverResponseType.success


def test_a_failed_connect_reports_the_reason_and_stays_unready():
    driver = BiologicEclib2Driver({"address": "", "simulate": False})
    try:
        response = driver.connect()
        assert response.response == DriverResponseType.failed
        assert response.status == DriverStatus.error
        assert "sdk_path is required" in response.message
        assert driver.ready is False
    finally:
        driver.shutdown()


def test_disconnect_then_reset_reconnects(connected):
    assert connected.disconnect().response == DriverResponseType.success
    assert connected.ready is False
    assert connected.reset().response == DriverResponseType.success
    assert connected.ready is True


def test_an_unknown_channel_is_refused_rather_than_created(connected):
    assert connected.setup("OCV", channel=7).response == DriverResponseType.failed
    assert connected.start_channel(7).response == DriverResponseType.failed
    assert connected.cleanup(7).response == DriverResponseType.failed
    assert connected.get_status(channel=7).status == DriverStatus.uninitialized


# --------------------------------------------------------------------------
# setup
# --------------------------------------------------------------------------


def test_setup_reports_the_techniques_the_plan_expanded_to(connected):
    response = connected.setup("PEIS", action_params=params("PEIS"))
    assert response.response == DriverResponseType.success
    # A PEIS action is a CA bias leg plus the sweep.
    assert response.data["techniques"] == [
        "EC_SDK_TECHNIQUE_CA",
        "EC_SDK_TECHNIQUE_PEIS",
    ]
    assert response.data["columns"] == list(ec2data.EIS_COLUMNS)


def test_setup_with_a_bad_parameter_fails_and_names_it(connected):
    bad = params("OCV")
    del bad["Tval__s"]
    response = connected.setup("OCV", action_params=bad)
    assert response.response == DriverResponseType.failed
    assert "Tval__s" in response.message


def test_setup_with_an_unknown_technique_fails(connected):
    response = connected.setup("VSCAN", action_params={})
    assert response.response == DriverResponseType.failed
    assert "VSCAN" in response.message


def test_starting_a_channel_that_was_never_set_up_is_refused(connected):
    response = connected.start_channel(CHANNEL)
    assert response.response == DriverResponseType.failed
    assert "not been set up" in response.message


def test_start_reports_busy_and_a_start_time(connected):
    connected.setup("OCV", action_params=params("OCV"))
    response = connected.start_channel(CHANNEL)
    assert response.status == DriverStatus.busy
    assert response.data["start_time"] > 0
    assert connected.get_status(channel=CHANNEL).status == DriverStatus.busy


def test_setup_is_refused_while_the_channel_is_running(connected):
    connected.setup("CAOCV", action_params=params("CAOCV"))
    connected.start_channel(CHANNEL)
    response = connected.setup("OCV", action_params=params("OCV"))
    assert response.response == DriverResponseType.failed
    assert "busy" in response.message


# --------------------------------------------------------------------------
# acquisition
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ec2tech.TECHNIQUE_NAMES)
def test_every_technique_acquires_and_emits_its_contract_columns(connected, name):
    table, response = asyncio.run(_run(connected, name))
    assert set(table) == set(connected.emitted_columns(name))
    lengths = {len(v) for v in table.values()}
    assert len(lengths) == 1, "columns must stay the same length"
    assert lengths.pop() > 0
    assert response.status == DriverStatus.ok


def test_get_data_marks_measuring_until_the_channel_goes_idle(connected):
    async def go():
        connected.setup("CAOCV", action_params=params("CAOCV"))
        connected.start_channel(CHANNEL)
        messages = []
        for _ in range(50):
            response = await connected.get_data(CHANNEL)
            messages.append(response.message)
            if response.message == "done":
                break
        return messages

    messages = asyncio.run(go())
    assert messages[-1] == "done"
    assert set(messages[:-1]) <= {"measuring"}


def test_get_data_before_setup_fails_rather_than_returning_empty(connected):
    response = asyncio.run(connected.get_data(CHANNEL))
    assert response.response == DriverResponseType.failed
    assert "not been set up" in response.message


def test_the_drain_loop_is_bounded(connected):
    # A channel producing rows faster than we read must not hold get_data, and
    # the single SDK worker thread, forever.
    connected.setup("OCV", action_params=params("OCV"))
    connected.start_channel(CHANNEL)

    calls = {"n": 0}
    real_poll = connected._client.poll

    def endless(channel):
        calls["n"] += 1
        result = real_poll(channel)
        # Always claim a row is present and the channel is running.
        return type(result)(
            running=True,
            rows=1,
            table={c: [0.0] for c in ec2data.OCV_COLUMNS},
            technique_index=0,
            technique_identifier="EC_SDK_TECHNIQUE_OCV",
        )

    connected._client.poll = endless
    try:
        response = asyncio.run(connected.get_data(CHANNEL))
    finally:
        connected._client.poll = real_poll

    assert calls["n"] == MAX_DRAINS_PER_CALL
    # Truncated, so not reported done -- otherwise the action would finish
    # while the instrument still held data.
    assert response.message == "measuring"
    assert len(response.data["t_s"]) == MAX_DRAINS_PER_CALL


def test_an_impedance_run_carries_both_legs_and_the_derived_columns(connected):
    table, _ = asyncio.run(_run(connected, "PEIS"))
    assert set(table["process"]) == {0, 1}
    # R_ohm/X_ohm are derived here, not reported by EClib2.
    sweep = [
        (r, x, m, p)
        for r, x, m, p in zip(
            table["R_ohm"], table["X_ohm"], table["modulus"], table["process"]
        )
        if p == 1
    ]
    assert sweep
    for r, x, m, _ in sweep:
        assert m == pytest.approx(5.0)
        assert r == pytest.approx(5.0 * math.cos(0.5))
        assert x == pytest.approx(-5.0 * math.sin(0.5))


def test_a_caocv_run_pads_the_ocv_leg_rather_than_reporting_zero_current(connected):
    table, _ = asyncio.run(_run(connected, "CAOCV"))
    assert any(math.isnan(v) for v in table["I_A"])
    assert not all(math.isnan(v) for v in table["I_A"])


# --------------------------------------------------------------------------
# stop, cleanup, introspection
# --------------------------------------------------------------------------


def test_stop_ends_a_running_channel(connected):
    connected.setup("CAOCV", action_params=params("CAOCV"))
    connected.start_channel(CHANNEL)
    assert connected.stop(channel=CHANNEL).response == DriverResponseType.success
    assert connected.get_status(channel=CHANNEL).status == DriverStatus.ok


def test_stop_with_no_channel_stops_every_set_up_channel(connected):
    connected.setup("CAOCV", action_params=params("CAOCV"))
    connected.start_channel(CHANNEL)
    assert connected.stop().response == DriverResponseType.success
    stops = [c for c in connected._client._api.calls if c[0] == "BL_StopChannel"]
    assert stops


def test_stop_before_connecting_is_not_an_error(driver):
    response = driver.stop()
    assert response.response == DriverResponseType.success
    assert response.status == DriverStatus.uninitialized


def test_cleanup_clears_the_plan_and_params(connected):
    connected.setup("CA", action_params=params("CA"))
    assert connected.channel_technique[CHANNEL] == "CA"
    assert connected.cleanup(CHANNEL).response == DriverResponseType.success
    assert connected.channel_technique[CHANNEL] is None
    assert connected.channel_params[CHANNEL] == {}
    assert connected.list_techniques(CHANNEL) == []


def test_cleanup_is_refused_while_running(connected):
    connected.setup("CAOCV", action_params=params("CAOCV"))
    connected.start_channel(CHANNEL)
    response = connected.cleanup(CHANNEL)
    assert response.response == DriverResponseType.failed
    assert "busy" in response.message


def test_list_techniques_reports_the_expansion_in_order(connected):
    connected.setup("GEIS", action_params=params("GEIS"))
    assert connected.list_techniques(CHANNEL) == [
        (0, "EC_SDK_TECHNIQUE_CP"),
        (1, "EC_SDK_TECHNIQUE_GEIS"),
    ]


def test_update_parameters_rebuilds_the_experiment(connected):
    connected.setup("CA", action_params=params("CA"))
    response = connected.update_parameters(CHANNEL, {"Vval__V": 0.9})
    assert response.response == DriverResponseType.success
    assert connected.channel_params[CHANNEL]["Vval__V"] == 0.9
    # Unchanged keys survive the merge.
    assert connected.channel_params[CHANNEL]["AcqInterval__A"] == 1e-3
    tech = list(connected._client._api.techniques.values())[-1]
    assert tech.params["EC_SDK_VOLTAGE_STEP_IN_V"] == [0.9]


def test_update_parameters_is_refused_while_running(connected):
    # Reloading an experiment under a live acquisition would silently discard
    # it.
    connected.setup("CAOCV", action_params=params("CAOCV"))
    connected.start_channel(CHANNEL)
    response = connected.update_parameters(CHANNEL, {"OCV_Tval__s": 9.0})
    assert response.response == DriverResponseType.failed
    assert "running" in response.message


def test_update_parameters_before_setup_is_refused(connected):
    response = connected.update_parameters(CHANNEL, {"Vval__V": 0.1})
    assert response.response == DriverResponseType.failed
    assert "not been set up" in response.message


def test_shutdown_closes_the_worker_thread(connected):
    connected.shutdown()
    assert connected._client is None
    assert connected.ready is False


# --------------------------------------------------------------------------
# drop-in parity
# --------------------------------------------------------------------------


def test_the_emitted_columns_match_the_eclib1_backend_for_every_technique():
    # Spelled out rather than imported from biologic/technique.py, whose
    # module-scope `easy_biologic` import would not load here. These are that
    # module's field_map values, plus the two the EClib1 driver's get_data
    # derives for impedance runs.
    eclib1 = {
        "OCV": {"t_s", "Ewe_V"},
        "CA": {"t_s", "Ewe_V", "I_A", "P_W", "cycle"},
        "CP": {"t_s", "Ewe_V", "I_A", "P_W", "cycle"},
        "CV": {"t_s", "Ewe_V", "I_A", "P_W", "cycle"},
        "CAOCV": {"t_s", "Ewe_V", "I_A", "P_W", "cycle"},
        "PEIS": {
            "process",
            "t_s",
            "Ewe_V",
            "I_A",
            "AbsEwe_V",
            "AbsI_A",
            "phase",
            "modulus",
            "Ece_V",
            "AbsEce_V",
            "AbsIce_A",
            "phase_ce",
            "modulus_ce",
            "f_Hz",
            "X_ohm",
            "R_ohm",
        },
        "GEIS": {
            "process",
            "t_s",
            "Ewe_V",
            "I_A",
            "AbsEwe_V",
            "AbsI_A",
            "phase",
            "modulus",
            "Ece_V",
            "AbsEce_V",
            "AbsIce_A",
            "phase_ce",
            "modulus_ce",
            "f_Hz",
            "X_ohm",
            "R_ohm",
        },
    }
    driver = BiologicEclib2Driver({})
    try:
        for name, columns in eclib1.items():
            assert set(driver.emitted_columns(name)) == columns, name
        # And nothing is missing from the map.
        assert set(eclib1) == set(ec2tech.TECHNIQUE_NAMES)
    finally:
        driver.shutdown()


def test_the_driver_exposes_the_eclib1_method_surface():
    for name in [
        "connect",
        "get_status",
        "setup",
        "start_channel",
        "get_data",
        "stop",
        "cleanup",
        "disconnect",
        "reset",
        "update_parameters",
        "list_techniques",
    ]:
        assert callable(getattr(BiologicEclib2Driver, name, None)), name


def test_start_channel_takes_no_ttl_params():
    # EClib2 has no TTL or digital-output capability at all, so the EClib1
    # signature cannot be honoured. A silently-ignored ttl_params would be
    # worse: a station would believe it was triggering.
    import inspect

    signature = inspect.signature(BiologicEclib2Driver.start_channel)
    assert "ttl_params" not in signature.parameters
