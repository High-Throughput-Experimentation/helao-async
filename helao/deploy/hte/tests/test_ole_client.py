"""The typed wrapper over EC-Lab's OLE COM functions.

Every OLE function returns a bare 1/0 with no reason attached, and section 2
of the manual states the interface performs no validation of anything sent.
The wrapper's whole value is therefore diagnostic: a 0 becomes a named failure
that says what is likely wrong, because the vendor never will.

The COM object is injected, so these tests run on Linux with no comtypes.
"""

import pytest

from helao.deploy.hte.drivers.pstat.biologic_ole.olecom_client import (
    HINTS,
    OleComClient,
    OleComError,
)


class FakeCom:
    """Records calls and replays scripted returns, in the tuple convention."""

    def __init__(self, returns=None):
        self.returns = returns or {}
        self.calls = []

    def __getattr__(self, name):
        def _call(*args):
            self.calls.append((name, args))
            value = self.returns.get(name, 1)
            return value(*args) if callable(value) else value

        return _call


def client(returns=None) -> tuple[OleComClient, FakeCom]:
    com = FakeCom(returns)
    return OleComClient(factory=lambda progid: com), com


def test_the_com_object_is_created_lazily_from_the_progid():
    created = []
    OleComClient(progid="X.Y", factory=lambda p: created.append(p) or object())
    assert created == []  # nothing until first use


def test_the_progid_reaches_the_factory_on_first_call():
    created = []

    def factory(progid):
        created.append(progid)
        return FakeCom()

    OleComClient(progid="EC-Lab.App", factory=factory).enable_messages_windows(False)
    assert created == ["EC-Lab.App"]


def test_connect_device_by_ip_returns_the_device_number():
    cli, com = client({"ConnectDeviceByIP": (1, 6)})
    assert cli.connect_device_by_ip("192.168.200.100") == 6
    assert com.calls == [("ConnectDeviceByIP", ("192.168.200.100",))]


def test_a_zero_return_raises_with_the_function_named():
    cli, _ = client({"ConnectDeviceByIP": (0, 0)})
    with pytest.raises(OleComError) as excinfo:
        cli.connect_device_by_ip("192.168.200.100")
    assert excinfo.value.function == "ConnectDeviceByIP"
    assert "192.168.200.100" in str(excinfo.value)


def test_the_failure_carries_the_documented_hint():
    cli, _ = client({"LoadSettings": 0})
    with pytest.raises(OleComError, match="incompatible with"):
        cli.load_settings(6, 3, "C:/x.mps")


def test_every_wrapped_function_has_a_hint():
    """A 0 with no hint is exactly the un-diagnosable failure this avoids."""
    wrapped = {
        "ConnectDeviceByIP",
        "DisconnectDevice",
        "LoadSettings",
        "RunChannel",
        "GetDataFileName",
        "MeasureStatus",
        "MeasureNumberOfPoints",
        "MeasureDcValue",
        "MeasureEisValue",
        "MeasureValueByCode",
        "GetDeviceChannelList",
        "GetDeviceType",
        "GetDeviceSN",
        "GetSoftwareVersion",
        "EnableMessagesWindows",
    }
    assert wrapped <= set(HINTS), sorted(wrapped - set(HINTS))


def test_stop_channel_reports_already_stopped_without_raising():
    """A 0 here means the channel was already stopped -- not an error."""
    cli, _ = client({"StopChannel": 0})
    assert cli.stop_channel(6, 3) is False


def test_is_channel_ready_and_test_connection_return_false_not_raise():
    cli, _ = client({"IsChannelReady": 0, "TestConnection": 0})
    assert cli.is_channel_ready(6, 3) is False
    assert cli.test_connection(6) is False


def test_measure_status_returns_the_32_reals():
    values = tuple(float(i) for i in range(32))
    cli, _ = client({"MeasureStatus": (1, values)})
    assert cli.measure_status(6, 3) == values


def test_measure_number_of_points_returns_the_count_not_a_success_flag():
    """MeasureNumberOfPoints' Result *is* the count, per section 5.2.12."""
    cli, _ = client({"MeasureNumberOfPoints": 47})
    assert cli.measure_number_of_points("C:/x.mpr") == 47


def test_zero_points_is_a_count_not_a_failure():
    cli, _ = client({"MeasureNumberOfPoints": 0})
    assert cli.measure_number_of_points("C:/x.mpr") == 0


def test_measure_dc_value_returns_the_array():
    cli, _ = client({"MeasureDcValue": (1, (0.3, -0.026, 1e-4))})
    assert cli.measure_dc_value("C:/x.mpr", 3) == (0.3, -0.026, 1e-4)


def test_measure_eis_value_returns_four_values():
    cli, _ = client({"MeasureEisValue": (1, (0.3, 1000.0, 52.0, -11.0))})
    assert cli.measure_eis_value("C:/x.mpr", 3) == (0.3, 1000.0, 52.0, -11.0)


def test_measure_value_by_code_returns_the_datum():
    cli, _ = client({"MeasureValueByCode": (1, -0.0259855, 1)})
    assert cli.measure_value_by_code("C:/x.mpr", 6, 3) == pytest.approx(-0.0259855)


def test_measure_value_by_code_honours_its_trailing_function_result():
    """Section 5.2.15: Result == FunctionResult, and Data precedes it."""
    cli, _ = client({"MeasureValueByCode": (0, 0.0, 0)})
    with pytest.raises(OleComError, match="MeasureValueByCode"):
        cli.measure_value_by_code("C:/x.mpr", 6, 3)


def test_get_device_channel_list_returns_booleans():
    flags = (0, 1, 0, 1) + (0,) * 12
    cli, _ = client({"GetDeviceChannelList": (1, flags)})
    assert cli.get_device_channel_list(6) == [False, True, False, True, *([False] * 12)]


def test_get_device_sn_splits_device_and_module_serials():
    cli, _ = client({"GetDeviceSN": (1, 12345, (0, 39697, 0), 1)})
    assert cli.get_device_sn(6) == (12345, [0, 39697, 0])


def test_enable_messages_windows_sends_an_int_not_a_bool():
    """The signature takes SYSINT; passing True is not the documented type."""
    cli, com = client({"EnableMessagesWindows": (1, 1)})
    cli.enable_messages_windows(False)
    assert com.calls == [("EnableMessagesWindows", (0,))]


def test_the_module_does_not_import_comtypes_at_module_scope():
    import sys

    assert "comtypes" not in sys.modules
