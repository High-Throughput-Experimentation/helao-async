"""Opt-in digital-output options on the NI-DAQmx driver.

``do_active_low``, ``do_open_collector`` and ``shutdown_to_off`` are all off by
default; with none set the written values, channel setup and shutdown must be
identical to before. NI-DAQmx is a Windows-only SDK, so a fake module stands in.
"""

import asyncio

import pytest

from helao.core.error import ErrorCodes
from helao.deploy.hte.servers.nidaqmx import nidaqmx_driver as drv
from helao.deploy.hte.servers.nidaqmx.nidaqmx_driver import cNIMAX

LED = {"led1": "D/port0/line0"}
PUMP = {"pump1": "D/port0/line1"}
GAS = {"gas1": "D/port0/line2"}
LIQ = {"liq1": "D/port0/line3"}
HEAT = {"heat1": "D/port0/line4"}
TTL = {"ttl1": "D/port0/line5"}
ALL = {**LED, **PUMP, **GAS, **LIQ, **HEAT, **TTL}
BASE = {
    "dev_led": LED,
    "dev_pump": PUMP,
    "dev_gasvalve": GAS,
    "dev_liquidvalve": LIQ,
    "dev_heat": HEAT,
    "dev_ttl": TTL,
}


class _Log:
    def __init__(self):
        self.writes = []  # (port, value)
        self.drive = []  # (port, drive_type, phase)
        self.fail_ports = set()
        self.readback = {}  # port -> value returned by read


class _Chan:
    def __init__(self, log, port, phase):
        self._log, self._port, self._phase = log, port, phase

    @property
    def do_output_drive_type(self):
        return None

    @do_output_drive_type.setter
    def do_output_drive_type(self, v):
        self._log.drive.append((self._port, v, self._phase))


class _Task:
    def __init__(self, log):
        self._log = log
        self._port = None
        self.do_channels = self

    def add_do_chan(self, port, line_grouping=None):
        self._port = port
        return _Chan(self._log, port, "open")

    def write(self, cmds):
        if self._port in self._log.fail_ports:
            raise RuntimeError("boom")
        self._log.writes.append((self._port, cmds[0]))

    def read(self, number_of_samples_per_channel=1):
        return [self._log.readback.get(self._port, False)]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _DDT:
    OPEN_COLLECTOR = "OC"


@pytest.fixture
def log(monkeypatch):
    lg = _Log()
    fake = type("nidaqmx", (), {"Task": staticmethod(lambda: _Task(lg))})
    monkeypatch.setattr(drv, "nidaqmx", fake, raising=False)
    monkeypatch.setattr(
        drv, "LineGrouping", type("LG", (), {"CHAN_PER_LINE": 1}), raising=False
    )
    monkeypatch.setattr(drv, "DigitalDriveType", _DDT, raising=False)
    return lg


def _make(**opts):
    d = cNIMAX(config={**BASE, **opts})
    disc = []
    orig = d.disconnect

    def _disc():
        disc.append(1)
        return orig()

    d.disconnect = _disc  # type: ignore[method-assign]
    d.disc = disc  # type: ignore[attr-defined]
    return d


def _set(d, name, on):
    return asyncio.run(d.set_digital_out(do_port=ALL[name], do_name=name, on=on))


def test_defaults_identical_writes_no_drive_type_no_shutdown_writes(log):
    d = _make()
    _set(d, "led1", True)
    _set(d, "pump1", False)
    assert log.writes == [(ALL["led1"], True), (ALL["pump1"], False)]
    asyncio.run(d.get_digital_out(do_port=ALL["led1"], do_name="led1"))
    assert log.drive == []
    log.writes.clear()
    asyncio.run(d.async_shutdown())
    assert log.writes == []
    assert len(getattr(d, "disc")) == 1


def test_active_low_inverts_write_readback_keeps_logical_state(log):
    d = _make(do_active_low=["pump1"])
    _set(d, "pump1", True)
    _set(d, "led1", True)
    assert log.writes == [(ALL["pump1"], False), (ALL["led1"], True)]
    assert d.do_state == {"pump1": True, "led1": True}
    log.readback[ALL["pump1"]] = False  # physical LOW == logical ON
    log.readback[ALL["led1"]] = True
    r = asyncio.run(d.get_digital_out(do_port=ALL["pump1"], do_name="pump1"))
    assert r["error_code"] == ErrorCodes.none and r["value"] == [True]
    r = asyncio.run(d.get_digital_out(do_port=ALL["led1"], do_name="led1"))
    assert r["value"] == [True]
    # do_state keeps the logical value after an off write too
    _set(d, "pump1", False)
    assert log.writes[-1] == (ALL["pump1"], True) and d.do_state["pump1"] is False


def test_active_low_applies_with_do_port_only(log):
    d = _make(do_active_low=["pump1"])
    asyncio.run(d.set_digital_out(do_port=ALL["pump1"], on=True))
    assert log.writes == [(ALL["pump1"], False)]


def test_estop_writes_high_on_active_low_both_edges(log):
    d = _make(do_active_low=["pump1", "ttl1"])
    for sw in (True, False):
        log.writes.clear()
        asyncio.run(d.estop(sw))
        got = dict(log.writes)
        assert len(log.writes) == len(ALL)
        for name, port in ALL.items():
            assert got[port] is (name in ("pump1", "ttl1")), name


def test_open_collector_listed_lines_only_on_write_and_readback(log):
    d = _make(do_open_collector=["led1"])
    _set(d, "led1", True)
    _set(d, "pump1", True)
    asyncio.run(d.get_digital_out(do_port=ALL["led1"], do_name="led1"))
    asyncio.run(d.get_digital_out(do_port=ALL["pump1"], do_name="pump1"))
    assert [(p, t) for p, t, _ in log.drive] == [(ALL["led1"], "OC")] * 2


def test_open_collector_true_covers_all_lines(log):
    d = _make(do_open_collector=True)
    for n in ALL:
        _set(d, n, True)
    assert sorted(p for p, _, _ in log.drive) == sorted(ALL.values())
    assert all(t == "OC" for _, t, _ in log.drive)


def test_shutdown_to_off_writes_logical_off_per_line_polarity(log):
    d = _make(shutdown_to_off=True, do_active_low=["pump1"])
    asyncio.run(d.async_shutdown())
    got = dict(log.writes)
    assert len(log.writes) == len(ALL)
    for name, port in ALL.items():
        assert got[port] is (name == "pump1"), name
    assert len(getattr(d, "disc")) == 1


def test_shutdown_to_off_failure_does_not_stop_others_or_disconnect(log):
    d = _make(shutdown_to_off=True)
    log.fail_ports.add(ALL["led1"])
    asyncio.run(d.async_shutdown())
    assert {p for p, _ in log.writes} == set(ALL.values()) - {ALL["led1"]}
    assert len(getattr(d, "disc")) == 1


@pytest.mark.parametrize("key", ["do_active_low", "do_open_collector"])
def test_unknown_name_or_wrong_type_raises(key):
    with pytest.raises(ValueError, match="nope"):
        _make(**{key: ["nope"]})
    with pytest.raises(ValueError):
        _make(**{key: {"led1": 1}})
    with pytest.raises(ValueError):
        _make(**{key: [{"a": 1}]})


def test_invert_keeps_nesting():
    assert drv._invert([[True, False]]) == [[False, True]]


EXTRA = {
    "dev_multivalve": {"mv1": "D/port1/line0"},
    "dev_mastercell": {"mc1": "D/port1/line1"},
    "dev_activecell": {"ac1": "D/port1/line2"},
    "dev_fswbcd": {"fs1": "D/port1/line3"},
}


def test_all_server_do_groups_accepted_and_applied(log):
    d = _make(
        **EXTRA, do_active_low=["mv1"], do_open_collector=True, shutdown_to_off=True
    )
    asyncio.run(d.set_digital_out(do_port="D/port1/line0", do_name="mv1", on=True))
    assert log.writes == [("D/port1/line0", False)]
    assert ("D/port1/line0", "OC", "open") in log.drive
    log.writes.clear()
    log.drive.clear()
    asyncio.run(d.async_shutdown())
    got = dict(log.writes)
    for g in EXTRA.values():
        for port in g.values():
            assert port in got
            assert {p for p, _, _ in log.drive} >= set(got)
    assert got["D/port1/line0"] is True and got["D/port1/line1"] is False
