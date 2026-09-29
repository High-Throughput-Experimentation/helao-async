"""Connection lifecycle against the simulated DLL."""

import pytest

from helao.core.drivers.helao_driver import (
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)
from helao.deploy.hte.drivers.pstat.biologic import sim, vendor
from helao.deploy.hte.drivers.pstat.biologic.driver import BiologicDriver

CONFIG = {
    "address": "192.168.200.100",
    "num_channels": 2,
    "simulate": True,
    "sdk_path": "/unused",
}


@pytest.fixture
def driver():
    sim.set_sim_config(sim.SimConfig())
    d = BiologicDriver(dict(CONFIG))
    try:
        yield d
    finally:
        d.shutdown()
        sim.set_sim_config(sim.SimConfig())


@pytest.fixture
def connected(driver):
    assert driver.connect().response == DriverResponseType.success
    return driver


def test_it_is_a_helao_driver():
    assert issubclass(BiologicDriver, HelaoDriver)


def test_construction_does_no_device_io():
    """P3a-2: the server constructs the driver, then calls connect()."""
    d = BiologicDriver(dict(CONFIG))
    assert d.ready is False
    assert d.channel is None
    assert d.get_status().status == DriverStatus.uninitialized


def test_construction_needs_no_sdk_and_no_instrument():
    d = BiologicDriver({"address": "10.0.0.1", "sdk_path": "/nonexistent"})
    assert d.ready is False


def test_the_config_defaults_are_the_ones_the_station_configs_rely_on():
    d = BiologicDriver({})
    assert d.address == "192.168.200.240"
    assert d.num_channels == 12
    assert d.sdk_path == vendor.DEFAULT_SDK_PATH


def test_connect_reports_ok_and_records_the_board_type(connected):
    assert connected.ready is True
    assert connected.board_type == vendor.BOARD_TYPE.PREMIUM


def test_connect_logs_a_device_name_that_names_the_firmware(connected):
    assert connected.device_name != "unknown"


def test_firmware_is_not_loaded_when_the_kernel_is_already_there(driver):
    """The vendor example forces a reload on every connect, which reflashes a
    production instrument.

    Rewritten from the brief's version (asserting against a spy `calls` list
    populated only *after* `connect()` ran, which is necessarily empty): that
    form passes even against a driver that reflashes on every connect. This
    asserts the actual load counter instead.
    """
    sim.set_sim_config(sim.SimConfig(kernel_loaded=True))
    driver.connect()
    assert sim.firmware_loads() == 0


def test_firmware_is_loaded_when_the_channel_reports_none(driver):
    sim.set_sim_config(sim.SimConfig(kernel_loaded=False))
    resp = driver.connect()
    assert resp.response == DriverResponseType.success
    assert sim.firmware_loads() == 1
    # The flags the DLL actually received, not just that a call happened --
    # BL_LoadFirmware's ABI is (..., ShowGauge, ForceReload, ...) and the two
    # were swapped (I1), which no call-count assertion could ever catch.
    assert sim.firmware_load_flags() == (False, False)


def test_firmware_is_loaded_when_the_channel_reports_a_non_kernel_code(driver):
    """FirmwareCode is a vendor enum, not a bool -- ECAL (10), which a
    calibration can leave a channel in, is neither NONE (0) nor KERNEL (5), so
    `_kernel_loaded` must read false and connect() must (re)load the kernel."""
    sim.set_sim_config(sim.SimConfig(firmware_code=10))
    resp = driver.connect()
    assert resp.response == DriverResponseType.success
    assert sim.firmware_loads() == 1


def test_firmware_path_joins_a_real_name_but_passes_an_empty_sentinel_through():
    """DIGICORE's FPGA slot is `""` (`vendor.firmware_assets`'s own sentinel
    for "no FPGA file"), not a bare filename -- `os.path.join(sdk_path, "")`
    yields `f"{sdk_path}/"`, which is not empty and tells the DLL to look for
    a file that does not exist. The simulator ignores `xlxfile` entirely, so
    only a direct test of the join catches a regression here."""
    from helao.deploy.hte.drivers.pstat.biologic.driver import _firmware_path

    assert _firmware_path("/sdk", "kernel.bin") == "/sdk/kernel.bin"
    assert _firmware_path("/sdk", "") == ""


def test_force_load_firmware_reloads_even_when_present():
    sim.set_sim_config(sim.SimConfig(kernel_loaded=True))
    d = BiologicDriver({**CONFIG, "force_load_firmware": True})
    try:
        d.connect()
        assert sim.firmware_loads() == 1
        assert sim.firmware_load_flags() == (False, True)
    finally:
        d.shutdown()


def test_a_busy_instrument_reports_busy_not_error(driver):
    """ERR_GEN_ECLAB_LOADED means EC-Lab is holding it. The old driver matched
    on the string "In use by another script"; this keys on the code."""
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_Connect": -9}))
    resp = driver.connect()
    assert resp.response == DriverResponseType.failed
    assert resp.status == DriverStatus.busy


def test_any_other_connect_failure_reports_error(driver):
    # -200 (ERR_COMM_COMMFAILED), not the brief's -102: Task 1's PDF
    # cross-check moved -102 to ERR_INSTR_TOOMANYDATA, which is not a comm
    # failure. -200 reads as the connect failure this test means.
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_Connect": -200}))
    resp = driver.connect()
    assert resp.status == DriverStatus.error


def test_a_failed_connect_leaves_the_driver_reconnectable(driver):
    """`connection_raised` was set before the attempt, so a throwing connect
    stranded the driver until the process restarted."""
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_Connect": -102}))
    assert driver.connect().status == DriverStatus.error
    sim.set_sim_config(sim.SimConfig())
    assert driver.connect().response == DriverResponseType.success


def test_a_second_connect_on_a_live_connection_is_a_successful_no_op(connected):
    assert connected.connect().response == DriverResponseType.success
    assert connected.ready is True


def test_get_status_reports_every_channel_when_given_none(connected):
    resp = connected.get_status()
    assert set(resp.data) == {0, 1}
    assert resp.status == DriverStatus.ok


def test_get_status_reports_one_channel_when_given_an_index(connected):
    resp = connected.get_status(channel=1)
    assert set(resp.data) == {1}


def test_get_status_on_a_nonexistent_channel_is_uninitialized(connected):
    resp = connected.get_status(channel=7)
    assert resp.status == DriverStatus.uninitialized
    assert resp.data == {}


def test_get_status_reports_busy_while_a_channel_runs(connected):
    # The brief's version calls `_client.start_channel(0)` with no technique
    # ever loaded on the channel; the sim (correctly mirroring the real DLL)
    # refuses BL_StartChannel with ERR_TECH_LOADTECHNIQUEFAILED in that case.
    # Load an empty-params OCV technique first, via the raw client, so this
    # stays inside the connection-half driver under test here rather than
    # reaching into setup() (Task 14). OCV specifically, and deliberately:
    # it's the one technique that never drives the cell, so if this shape
    # ever gets copied toward real hardware it copies the non-perturbing one.
    sim.set_sim_config(sim.SimConfig(polls_until_stop=99))
    connected._client.load_technique(
        0, "ocv.ecc", connected._client.define_params([]), True, True
    )
    connected._client.start_channel(0)
    assert connected.get_status().status == DriverStatus.busy


def test_disconnect_clears_ready_and_the_claim(connected):
    assert connected.disconnect().response == DriverResponseType.success
    assert connected.ready is False
    assert connected.channel is None


def test_reset_reconnects_and_reports_the_reconnect_result(connected):
    assert connected.reset().response == DriverResponseType.success
    assert connected.ready is True


def test_reset_reports_failure_when_the_reconnect_fails(connected):
    """The old reset() built a success response and then reconnected in a
    finally, so a failed reconnect reported success."""
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_Connect": -102}))
    resp = connected.reset()
    assert resp.response == DriverResponseType.failed
    assert connected.ready is False


def test_shutdown_is_safe_on_a_driver_that_never_connected():
    BiologicDriver(dict(CONFIG)).shutdown()


def test_shutdown_is_idempotent(connected):
    connected.shutdown()
    connected.shutdown()
    assert connected.ready is False


def test_firmware_messages_are_drained_on_status_polls(connected, caplog):
    sim.push_message(0, "I_Range out of range, clamped")
    with caplog.at_level("WARNING"):
        connected.get_status(channel=0)
    assert any("clamped" in r.message for r in caplog.records)


def test_connect_reloads_the_kernel_when_the_channel_reports_none(monkeypatch):
    """`BL_GetChannelInfos` needs the kernel it reports on, so a channel whose
    firmware has crashed answers `ERR_FIRM_FIRMWARENOTLOADED` rather than a
    zero `FirmwareCode`. Read as a failure that made the channel
    unrecoverable: connect aborted on the probe it uses to decide whether to
    reload. Seen at a station on 2026-09-18 after a `BL_LoadTechnique`
    returned -200 and took the channel's kernel with it."""
    from helao.deploy.hte.drivers.pstat.biologic.eclib_client import (
        EclibClient,
        EclibError,
    )

    sim.set_sim_config(sim.SimConfig(kernel_loaded=True))
    unpatched = EclibClient.channel_info
    calls = {"n": 0}

    def crashed_once(self, channel):
        calls["n"] += 1
        if calls["n"] == 1:
            raise EclibError(-308, "BL_GetChannelInfos")
        return unpatched(self, channel)

    monkeypatch.setattr(EclibClient, "channel_info", crashed_once)

    d = BiologicDriver(dict(CONFIG))
    try:
        assert d.connect().status == DriverStatus.ok
        assert sim.firmware_loads() == 1
    finally:
        d.shutdown()


def test_connect_still_fails_on_an_error_that_is_not_a_missing_kernel(monkeypatch):
    """Only -308 means "reload"; every other code stays a failed connect."""
    from helao.deploy.hte.drivers.pstat.biologic.eclib_client import (
        EclibClient,
        EclibError,
    )

    def refused(self, channel):
        raise EclibError(-200, "BL_GetChannelInfos")

    monkeypatch.setattr(EclibClient, "channel_info", refused)

    d = BiologicDriver(dict(CONFIG))
    try:
        assert d.connect().response == DriverResponseType.failed
        assert sim.firmware_loads() == 0
    finally:
        d.shutdown()
