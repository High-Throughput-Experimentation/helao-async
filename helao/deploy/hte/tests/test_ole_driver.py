"""BiologicOleDriver, end to end against the fake COM server.

The driver is the only module that knows the *order* of the OLE calls, and
the order carries most of the correctness: EnableMessagesWindows before
anything can block on a dialog, IsChannelReady and LoadSettings before
RunChannel, and -- the one that truncates records when wrong -- finishing only
at state Stop with one further drain, never at Stop_rec.
"""

import asyncio

import pytest

from helao.core.drivers.helao_driver import DriverResponseType, DriverStatus
from helao.deploy.hte.drivers.pstat.biologic_ole import technique as ot
from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver
from helao.deploy.hte.drivers.pstat.biologic_ole.sim import SimConfig, set_sim_config


@pytest.fixture(autouse=True)
def fast_sim():
    set_sim_config(SimConfig(run_seconds=0.0, points_per_second=100.0))
    yield
    set_sim_config(SimConfig())


def mps_row(label: str, *values: str) -> str:
    """One fixed-width .mps table row, as EC-Lab writes it (20 columns).

    Written this way rather than as a literal because the table is
    column-positional: a fixture with the wrong padding does not fail as a
    fixture, it fails as "the parser is broken".
    """
    return label.ljust(20) + "".join(v.ljust(20) for v in values) + "\n"


@pytest.fixture
def ca_template(tmp_path_factory):
    """A directory holding a minimal CA.mps the patcher can work on."""
    directory = tmp_path_factory.mktemp("templates")
    (directory / "CA.mps").write_text(
        "EC-LAB SETTING FILE\n\nNumber of linked techniques : 1\n\n"
        "Technique : 1\nChronoamperometry\n"
        + mps_row("Ei (V)", "0.000")
        + mps_row("ti (h:m:s)", "0:00:10.0000")
        + mps_row("dta (s)", "0.0100")
        + mps_row("dI", "10.000")
        + mps_row("unit dI", "mA")
        + mps_row("I Range", "Auto")
        + mps_row("E range min (V)", "-10.000")
        + mps_row("E range max (V)", "10.000")
        + mps_row("Bandwidth", "4"),
        encoding="latin-1",
    )
    return directory


def make_driver(**overrides) -> BiologicOleDriver:
    config = {"address": "192.168.200.100", "num_channels": 1, "simulate": True}
    config.update(overrides)
    return BiologicOleDriver(config=config)


def connected(**overrides) -> BiologicOleDriver:
    driver = make_driver(**overrides)
    assert driver.connect().response == DriverResponseType.success
    return driver


def test_construction_opens_nothing():
    """BaseAPI never calls connect(); the server does, at startup."""
    driver = make_driver()
    assert driver.ready is False


def test_connect_reports_success_and_marks_ready():
    driver = connected()
    assert driver.ready is True


def test_connect_suppresses_windows_message_boxes_first():
    """A modal dialog blocks the COM call that raised it, forever."""
    driver = connected()
    assert driver.client.com.messages_enabled is False


def test_connect_refuses_an_eclab_below_the_version_floor(monkeypatch):
    driver = make_driver()
    monkeypatch.setattr(
        type(driver), "_read_version", lambda self: "10.40", raising=False
    )
    response = driver.connect()
    assert response.response == DriverResponseType.failed
    assert "11.11" in response.message


def test_get_status_of_an_idle_channel_is_ok():
    driver = connected()
    response = driver.get_status(channel=0)
    assert response.status == DriverStatus.ok


def test_get_status_before_connect_is_uninitialized():
    assert make_driver().get_status().status == DriverStatus.uninitialized


def test_get_status_of_an_unknown_channel_is_uninitialized():
    assert connected().get_status(channel=9).status == DriverStatus.uninitialized


def test_setup_writes_a_patched_mps_and_loads_it(tmp_path):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(tmp_path))
    (tmp_path / "CA.mps").write_text(
        "Technique : 1\nChronoamperometry\n"
        + mps_row("Ei (V)", "0.000")
        + mps_row("ti (h:m:s)", "0:00:10.0000")
        + mps_row("dta (s)", "0.0100"),
        encoding="latin-1",
    )
    response = driver.setup(
        technique=ot.resolve("CA"),
        action_params={"channel": 0, "Vval__V": 0.75, "Tval__s": 5.0},
    )
    assert response.response == DriverResponseType.success
    template_path = tmp_path / "CA.mps"
    written = list(tmp_path.rglob("*.mps"))
    # The patched file is written under a uuid-scoped scratch subdirectory
    # but keeps the technique's own basename ("CA.mps"), identical to the
    # template's. Distinguish by path identity, not by name -- a name-only
    # filter excludes the patched file along with the template, leaving
    # nothing to assert on.
    patched = [p for p in written if p != template_path]
    assert len(patched) == 1
    written = patched[0].read_text(encoding="latin-1")
    assert "0.750" in written
    assert "0:00:5.0000" in written


def test_setup_refuses_a_channel_that_does_not_exist(tmp_path):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(tmp_path))
    response = driver.setup(technique=ot.resolve("CA"), action_params={"channel": 9})
    assert response.response == DriverResponseType.failed


def test_setup_refuses_a_channel_already_in_use(tmp_path, ca_template):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    params = {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0}
    assert driver.setup(ot.resolve("CA"), params).response == "success"
    assert driver.setup(ot.resolve("CA"), params).response == "failed"


def test_a_refused_load_settings_names_the_hardware_hint(tmp_path, ca_template):
    set_sim_config(SimConfig(run_seconds=0.0, refuse_load=True))
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    response = driver.setup(
        ot.resolve("CA"), {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0}
    )
    assert response.response == DriverResponseType.failed
    assert "incompatible" in response.message


def test_start_channel_reports_busy_and_a_start_time(tmp_path, ca_template):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    driver.setup(ot.resolve("CA"), {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0})
    response = driver.start_channel(0)
    assert response.status == DriverStatus.busy
    assert response.data["start_time"] > 0


def test_start_channel_refuses_a_channel_that_was_never_set_up():
    assert connected().start_channel(0).response == DriverResponseType.failed


def test_get_data_yields_points_and_finishes_at_done(tmp_path, ca_template):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    driver.setup(ot.resolve("CA"), {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0})
    driver.start_channel(0)
    messages, rows = [], 0
    for _ in range(10):
        response = asyncio.run(driver.get_data(0))
        messages.append(response.message)
        rows += len(response.data.get("t_s", []))
        if response.message == "done":
            break
    assert messages[-1] == "done"
    assert rows > 0


def test_the_recording_tail_is_not_reported_as_done(tmp_path, ca_template):
    """Stop_rec means 'writing the last points'. Finishing there truncates."""
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    driver.setup(ot.resolve("CA"), {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0})
    driver.start_channel(0)
    first = asyncio.run(driver.get_data(0))
    assert first.message == "measuring"


def test_the_emitted_columns_are_the_technique_s_declared_set(tmp_path, ca_template):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    driver.setup(ot.resolve("CA"), {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0})
    driver.start_channel(0)
    response = asyncio.run(driver.get_data(0))
    expected = set(ot.columns(ot.resolve("CA").column_plan))
    assert set(response.data) >= expected


def test_a_tripped_safety_limit_raises_an_alert_and_no_extra_column(
    tmp_path, ca_template, monkeypatch, caplog
):
    """The limit goes to LOGGER.alert, not into the data.

    Deliberately not a data column: the emitted column set is a frozen
    contract with two visualizer panels and five experiment libraries, and
    `test_biologic_column_contract.py` fails on any column the technique did
    not declare. A safety trip is an operator-facing event, not a datum.
    """
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    driver.setup(ot.resolve("CA"), {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0})
    driver.start_channel(0)
    original = driver.client.com.MeasureStatus

    def tripped(dev, ch):
        result, values = original(dev, ch)
        values = list(values)
        values[0] = 0.0  # Stop, so get_data takes the finishing branch
        values[30] = 1.0  # Emax
        return (result, tuple(values))

    monkeypatch.setattr(driver.client.com, "MeasureStatus", tripped)
    with caplog.at_level("WARNING"):
        response = asyncio.run(driver.get_data(0))
    assert response.message == "done"
    assert "EMAX" in caplog.text
    assert "_safety_limit" not in response.data


def test_stop_on_an_idle_channel_is_not_an_error():
    """StopChannel returns 0 when already stopped; that is an answer."""
    assert connected().stop(channel=0).response == DriverResponseType.success


def test_stop_with_no_channel_stops_every_running_one(tmp_path, ca_template):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    driver.setup(ot.resolve("CA"), {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0})
    driver.start_channel(0)
    assert driver.stop().response == DriverResponseType.success


def test_cleanup_clears_the_channel_so_it_can_be_set_up_again(tmp_path, ca_template):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    params = {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0}
    driver.setup(ot.resolve("CA"), params)
    assert driver.cleanup(0).response == DriverResponseType.success
    assert driver.setup(ot.resolve("CA"), params).response == "success"


def test_cleanup_moves_the_artifacts_into_the_action_directory(tmp_path, ca_template):
    """The .mps and .mpr ship as provenance -- moved after the run, not during."""
    action_dir = tmp_path / "action"
    action_dir.mkdir()
    driver = connected(
        scratch_dir=str(tmp_path / "scratch"), templates_dir=str(ca_template)
    )
    driver.setup(
        ot.resolve("CA"),
        {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0},
        output_dir=str(action_dir),
    )
    driver.start_channel(0)
    for _ in range(10):
        if asyncio.run(driver.get_data(0)).message == "done":
            break
    driver.cleanup(0)
    assert list(action_dir.glob("*.mps")), list(action_dir.iterdir())


def test_the_simulator_reports_the_configured_channel_count():
    """A multi-channel server must not out-range its own fake device.

    get_status() iterates range(num_channels); the sim defaults to one
    channel. Left unthreaded, a `num_channels: 2` config logged a traceback
    on every teardown -- caught inside get_status, so the group still shut
    down and nothing failed, which is exactly why it survived until a real
    `launch.py biologicole` run surfaced it.
    """
    driver = connected(num_channels=3)
    response = driver.get_status()
    assert response.response == DriverResponseType.success
    assert sorted(response.data) == [0, 1, 2]
    assert driver.disconnect().response == DriverResponseType.success


def test_a_test_supplied_sim_config_survives_the_channel_override():
    """The driver imposes n_channels without discarding run_seconds/kind."""
    set_sim_config(SimConfig(run_seconds=0.0, kind="eis", n_eis_points=7))
    driver = connected(num_channels=2)
    assert sorted(driver.get_status().data) == [0, 1]
    assert driver.client.com.config.kind == "eis"
    assert driver.client.com.config.n_eis_points == 7


def test_disconnect_clears_ready():
    driver = connected()
    assert driver.disconnect().response == DriverResponseType.success
    assert driver.ready is False


def test_reset_reconnects():
    driver = connected()
    assert driver.reset().response == DriverResponseType.success
    assert driver.ready is True


def test_shutdown_stops_cleans_up_and_disconnects(tmp_path, ca_template):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    driver.setup(ot.resolve("CA"), {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0})
    driver.start_channel(0)
    driver.shutdown()
    assert driver.ready is False


def test_the_module_imports_without_comtypes():
    import sys

    assert "comtypes" not in sys.modules
