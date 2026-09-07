"""The fake EC-Lab COM server.

EC-Lab and comtypes are Windows-only, so without this nothing in the package
past the pure text layer could be exercised at all. The fake reproduces the
*failure* behaviours as carefully as the happy path -- a LoadSettings that
never returns 0 would leave the diagnostic layer, which is most of the client,
untested.
"""

import pytest

from helao.deploy.hte.drivers.pstat.biologic_ole.olecom_client import (
    OleComClient,
    OleComError,
)
from helao.deploy.hte.drivers.pstat.biologic_ole.sim import SimConfig, make_factory
from helao.deploy.hte.drivers.pstat.biologic_ole.status import (
    ChannelState,
    decode_status,
)


def client(config: SimConfig | None = None) -> OleComClient:
    return OleComClient(factory=make_factory(config))


def test_the_client_drives_the_fake_end_to_end(tmp_path):
    cli = client(SimConfig(run_seconds=0.0))
    cli.enable_messages_windows(False)
    dev = cli.connect_device_by_ip("192.168.200.100")
    assert cli.test_connection(dev) is True
    assert cli.is_channel_ready(dev, 0) is True
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    assert cli.get_data_file_name(dev, 0, 0).endswith(".mpr")


def test_the_reported_software_version_clears_the_floor():
    assert client().get_software_version() == "11.72"


def test_a_channel_is_stopped_before_it_runs(tmp_path):
    cli = client()
    dev = cli.connect_device_by_ip("1.2.3.4")
    assert decode_status(cli.measure_status(dev, 0)).state is ChannelState.STOP


def test_a_running_channel_reports_run_then_stop(tmp_path):
    cli = client(SimConfig(run_seconds=0.05))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    assert decode_status(cli.measure_status(dev, 0)).is_busy is True
    import time

    time.sleep(0.08)
    # Stop_rec1 is one poll wide (see test_the_run_passes_through_the_recording_tail):
    # the first poll after run_seconds elapses reports it, and only the next
    # poll reports Stop.
    decode_status(cli.measure_status(dev, 0))
    assert decode_status(cli.measure_status(dev, 0)).state is ChannelState.STOP


def test_the_run_passes_through_the_recording_tail(tmp_path):
    """Stop_rec is a real state a poll loop must not read as finished."""
    cli = client(SimConfig(run_seconds=0.0))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    seen = {decode_status(cli.measure_status(dev, 0)).state for _ in range(4)}
    assert ChannelState.STOP_REC1 in seen
    assert ChannelState.STOP in seen


def test_the_status_technique_code_is_the_configured_one(tmp_path):
    cli = client(SimConfig(technique_code=11))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    assert decode_status(cli.measure_status(dev, 0)).technique_code == 11


def test_point_count_grows_while_running_and_settles(tmp_path):
    cli = client(SimConfig(run_seconds=0.05, points_per_second=200.0))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    mpr = cli.get_data_file_name(dev, 0, 0)
    first = cli.measure_number_of_points(mpr)
    import time

    time.sleep(0.08)
    settled = cli.measure_number_of_points(mpr)
    assert settled >= first
    assert cli.measure_number_of_points(mpr) == settled


def test_dc_points_are_monotonic_in_time(tmp_path):
    cli = client(SimConfig(run_seconds=0.0))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    mpr = cli.get_data_file_name(dev, 0, 0)
    n = cli.measure_number_of_points(mpr)
    times = [cli.measure_dc_value(mpr, i)[0] for i in range(n)]
    assert times == sorted(times)
    assert n > 0


def test_an_eis_file_serves_eis_values(tmp_path):
    cli = client(SimConfig(kind="eis", run_seconds=0.0, n_eis_points=5))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    mpr = cli.get_data_file_name(dev, 0, 0)
    assert cli.measure_number_of_points(mpr) == 5
    t_s, f_hz, re_z, minus_im_z = cli.measure_eis_value(mpr, 0)
    assert f_hz > 0
    assert re_z != 0


def test_measure_value_by_code_serves_the_documented_codes(tmp_path):
    cli = client(SimConfig(run_seconds=0.0))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    mpr = cli.get_data_file_name(dev, 0, 0)
    assert cli.measure_value_by_code(mpr, 4, 0) == pytest.approx(0.0)  # t_s
    assert cli.measure_value_by_code(mpr, 6, 0) != 0  # Ewe


def test_an_unrecorded_variable_code_is_refused(tmp_path):
    cli = client(SimConfig(run_seconds=0.0))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    mpr = cli.get_data_file_name(dev, 0, 0)
    with pytest.raises(OleComError, match="MeasureValueByCode"):
        cli.measure_value_by_code(mpr, 999, 0)


def test_an_index_past_the_end_is_refused(tmp_path):
    cli = client(SimConfig(run_seconds=0.0))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    mpr = cli.get_data_file_name(dev, 0, 0)
    with pytest.raises(OleComError, match="MeasureDcValue"):
        cli.measure_dc_value(mpr, 10_000)


def test_a_refused_load_raises_with_the_hardware_hint(tmp_path):
    cli = client(SimConfig(refuse_load=True))
    dev = cli.connect_device_by_ip("1.2.3.4")
    with pytest.raises(OleComError, match="incompatible with"):
        cli.load_settings(dev, 0, str(tmp_path / "x.mps"))


def test_running_without_loading_settings_is_refused(tmp_path):
    """RunChannel's documented failure: no settings loaded on the channel."""
    cli = client()
    dev = cli.connect_device_by_ip("1.2.3.4")
    with pytest.raises(OleComError, match="RunChannel"):
        cli.run_channel(dev, 0, str(tmp_path / "out"))


def test_stopping_an_idle_channel_answers_false_without_raising():
    cli = client()
    dev = cli.connect_device_by_ip("1.2.3.4")
    assert cli.stop_channel(dev, 0) is False


def test_an_unknown_device_number_is_refused():
    cli = client()
    with pytest.raises(OleComError, match="MeasureStatus"):
        cli.measure_status(99, 0)


def test_a_channel_beyond_the_configured_count_is_refused():
    cli = client(SimConfig(n_channels=1))
    dev = cli.connect_device_by_ip("1.2.3.4")
    with pytest.raises(OleComError, match="MeasureStatus"):
        cli.measure_status(dev, 5)


def test_the_channel_list_matches_the_configured_channel_count():
    cli = client(SimConfig(n_channels=3))
    dev = cli.connect_device_by_ip("1.2.3.4")
    flags = cli.get_device_channel_list(dev)
    assert flags[:3] == [True, True, True]
    assert not any(flags[3:])
