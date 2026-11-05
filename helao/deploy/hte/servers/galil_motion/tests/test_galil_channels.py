import pytest

from helao.deploy.hte.servers.galil_motion.galil_channels import (
    CHANNELS,
    make_channel,
)
from helao.deploy.hte.servers.galil_motion.galil_command_channel import (
    GclibCommandChannel,
)
from helao.deploy.hte.servers.galil_motion.galil_command_channel2 import (
    Gclib2CommandChannel,
)
from helao.deploy.hte.servers.galil_motion.galil_command_channel_port import (
    GalilChannelError,
    GalilCommandChannel,
)
from helao.deploy.hte.servers.galil_motion.tests.fake_gclib import Wire, install

CONN = "10.0.0.5 --direct -s ALL"


@pytest.mark.parametrize("api", ["1", "2"])
def test_same_wire_traffic_for_both_wrappers(monkeypatch, api):
    wire = Wire({"MG _TPA": "1000"})
    install(monkeypatch, api, wire)
    ch = CHANNELS[api]()
    assert isinstance(ch, GalilCommandChannel)
    ch.open(CONN)
    assert ch.command("MG _TPA") == "1000"
    ch.download_program("DL;")
    ch.download_program("#A\nEN\x00")
    ch.close()
    assert wire.calls == [
        ("open", "10.0.0.5"),
        ("command", "MG _TPA"),
        ("program", "DL;"),
        ("program", "#A\nEN"),
        ("close",),
    ]


def test_v1_download_is_passed_through_unchanged(monkeypatch):
    wire = Wire()
    install(monkeypatch, "1", wire)
    ch = GclibCommandChannel()
    ch.open(CONN)
    ch.download_program("#A\nEN\x00")
    assert wire.raw_programs == ["#A\nEN\x00"]


def test_v1_open_string_is_verbatim(monkeypatch):
    wire = Wire()
    install(monkeypatch, "1", wire)
    GclibCommandChannel().open(CONN)
    assert wire.raw_open == CONN


def test_v2_download_strips_only_trailing_nul(monkeypatch):
    wire = Wire()
    install(monkeypatch, "2", wire)
    ch = Gclib2CommandChannel()
    ch.open(CONN)
    ch.download_program("DL;")
    ch.download_program("#A\nEN\x00")
    ch.download_program("#A\nEN\x00\x00")
    assert wire.raw_programs == ["DL;", "#A\nEN", "#A\nEN\x00"]


def test_v2_direct_disables_gcaps(monkeypatch):
    wire = Wire()
    install(monkeypatch, "2", wire)
    Gclib2CommandChannel().open(CONN)
    assert wire.gcaps is False


def test_v2_without_direct_leaves_gcaps(monkeypatch):
    wire = Wire()
    install(monkeypatch, "2", wire)
    Gclib2CommandChannel().open("10.0.0.5")
    assert wire.gcaps is None


@pytest.mark.parametrize("api", ["1", "2"])
def test_info_and_version_shape(monkeypatch, api):
    install(monkeypatch, api, Wire())
    ch = CHANNELS[api]()
    ch.open(CONN)
    assert ch.info() == "10.0.0.5, DMC4183 Rev 1.3a, 12345"
    assert ch.version() == ("1.0.1" if api == "1" else "2.5.0")


def test_v2_info_and_version_errors_map(monkeypatch):
    wire = Wire()
    install(monkeypatch, "2", wire)
    ch = CHANNELS["2"]()
    ch.open(CONN)
    wire.info_error = True
    with pytest.raises(GalilChannelError, match="info failed"):
        ch.info()
    with pytest.raises(GalilChannelError, match="version failed"):
        ch.version()


@pytest.mark.parametrize("api", ["1", "2"])
def test_command_error_maps(monkeypatch, api):
    install(monkeypatch, api, Wire(fail_on={"BAD"}))
    ch = CHANNELS[api]()
    ch.open(CONN)
    with pytest.raises(GalilChannelError, match="BAD"):
        ch.command("BAD")


@pytest.mark.parametrize("api", ["1", "2"])
def test_open_error_maps(monkeypatch, api):
    wire = Wire()
    wire.open_error = True
    install(monkeypatch, api, wire)
    with pytest.raises(GalilChannelError):
        CHANNELS[api]().open(CONN)


test_v2_open_error_maps = test_open_error_maps  # Review Focus 3 name


@pytest.mark.parametrize("api", ["1", "2"])
def test_close_is_idempotent(monkeypatch, api):
    install(monkeypatch, api, Wire())
    ch = CHANNELS[api]()
    ch.close()  # before open
    ch.open(CONN)
    ch.close()
    ch.close()


@pytest.mark.parametrize("api", ["1", "2"])
def test_not_open_raises(monkeypatch, api):
    install(monkeypatch, api, Wire())
    ch = CHANNELS[api]()
    with pytest.raises(GalilChannelError, match="not open"):
        ch.command("TP")
    with pytest.raises(GalilChannelError, match="not open"):
        ch.download_program("DL;")


def test_wrong_wrapper_for_api_1(monkeypatch):
    install(monkeypatch, "2", Wire())
    with pytest.raises(GalilChannelError, match="gclib_api"):
        GclibCommandChannel().open(CONN)


def test_wrong_wrapper_for_api_2(monkeypatch):
    install(monkeypatch, "1", Wire())
    with pytest.raises(GalilChannelError, match="gclib_api"):
        Gclib2CommandChannel().open(CONN)


def test_default_is_v1():
    assert isinstance(make_channel({}), GclibCommandChannel)


@pytest.mark.parametrize("value", ["2", 2])
def test_int_api_is_normalised(value):
    assert isinstance(make_channel({"gclib_api": value}), Gclib2CommandChannel)


@pytest.mark.parametrize("value", ["3", "", True, None, 2.0, [2]])
def test_unknown_api_raises(value):
    with pytest.raises(ValueError, match="gclib_api"):
        make_channel({"gclib_api": value})
