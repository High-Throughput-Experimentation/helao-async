"""Config (raw-dict identity), Logging (fail-loud), Clock (NTP offset)."""

from datetime import datetime, timedelta

import pytest

from helao.hexagon.adapters.shared.clock import LegacyClockAdapter
from helao.hexagon.adapters.shared.config import LegacyConfigAdapter
from helao.hexagon.adapters.shared.logging_adapter import LegacyLoggingAdapter
from helao.hexagon.ports.clock import ClockPort
from helao.hexagon.ports.config import ConfigPort
from helao.hexagon.ports.logging import LoggingPort


# --- Config: raw-dict identity (spec §9.2) --------------------------------
def _world():
    return {
        "root": "/tmp/hex_t4",
        "servers": {"ORCH": {"host": "127.0.0.1", "port": 8001, "params": {"a": 1}}},
    }


def test_config_conformance_and_identity():
    cfg = _world()
    a = LegacyConfigAdapter(cfg)
    assert isinstance(a, ConfigPort)
    assert a.world_cfg() is cfg  # SAME object, every call
    assert a.world_cfg() is a.world_cfg()
    assert a.server_cfg("ORCH") is cfg["servers"]["ORCH"]  # --restore gate
    # in-place mutation through the view is visible in the source dict
    a.server_cfg("ORCH")["restore_queues_on_startup"] = True
    assert cfg["servers"]["ORCH"]["restore_queues_on_startup"] is True


def test_config_server_params_and_root():
    a = LegacyConfigAdapter(_world())
    assert a.server_params("ORCH") == {"a": 1}
    assert a.root() == "/tmp/hex_t4"
    with pytest.raises(KeyError):
        LegacyConfigAdapter({"servers": {}}).root()


# --- Logging: FAIL LOUD (F3) -----------------------------------------------
def test_logging_conformance():
    assert isinstance(LegacyLoggingAdapter(), LoggingPort)


def test_file_logger_raises_without_log_root(monkeypatch):
    import tempfile

    def _trap(*a, **k):  # the mkdtemp fallback must be unreachable
        raise AssertionError("tempfile.mkdtemp reached through the Logging port")

    monkeypatch.setattr(tempfile, "mkdtemp", _trap)
    a = LegacyLoggingAdapter()
    with pytest.raises(ValueError):
        a.file_logger("ORCH", "")
    with pytest.raises(ValueError):
        a.file_logger("ORCH", None)  # type: ignore[arg-type]


def test_file_logger_writes_contractual_path(tmp_path):
    a = LegacyLoggingAdapter()
    lg = a.file_logger("HEXT4", str(tmp_path))
    lg.info("hexagon logging adapter behavior test")  # type: ignore[attr-defined]
    logfile = tmp_path / "HEXT4.log"
    assert logfile.is_file()  # <log_root>/<server_key>.log, flat (spec §9.1)


def test_level_methods_delegate():
    rec: list = []

    class _Spy:
        def info(self, m):
            rec.append(("info", m))

        def warning(self, m):
            rec.append(("warning", m))

        def error(self, m, exc_info=False):
            rec.append(("error", m, exc_info))

        def alert(self, m):
            rec.append(("alert", m))

    a = LegacyLoggingAdapter(logger=_Spy())
    a.info("i")
    a.warning("w")
    a.error("e", exc_info=True)
    a.alert("a")
    assert rec == [
        ("info", "i"),
        ("warning", "w"),
        ("error", "e", True),
        ("alert", "a"),
    ]


# --- Clock ------------------------------------------------------------------
def test_clock_conformance_and_offset_math():
    a = LegacyClockAdapter(offset_s=2.0)
    assert isinstance(a, ClockPort)
    assert a.offset() == 2.0
    # now() is set_time(offset): ~2 s ahead of the naive wall clock
    delta = a.now() - datetime.now()
    assert timedelta(seconds=1.5) < delta < timedelta(seconds=2.5)
    span = a.now_ns() - a.now_ns()
    assert span <= 0  # monotone non-decreasing call order sanity
    assert abs(a.now_ns() - (a.now().timestamp() * 1e9)) < 0.5e9


def test_clock_from_offset_file(tmp_path):
    # ntpLastSync.txt format written by time_utils.get_ntp_time: "<ts>,<offset>"
    (tmp_path / "ntpLastSync.txt").write_text("1752700000.0,1.25", encoding="utf-8")
    a = LegacyClockAdapter.from_offset_file(str(tmp_path))
    assert a.offset() == 1.25


def test_clock_from_missing_offset_file(tmp_path):
    a = LegacyClockAdapter.from_offset_file(str(tmp_path))  # no file -> offset 0.0
    assert a.offset() == 0.0


def test_get_realtime_nowait_adds_the_ntp_offset_once(monkeypatch):
    """Headers used to sit 2*offset ahead of raw ``time.time()``.

    ``LegacyClockAdapter.now_ns`` already adds the offset. Adding it again in
    ``ActionHost.get_realtime_nowait`` made every HLO ``epoch_ns`` twice-
    corrected, which shifted Ocean ``epoch_s`` (raw ``time.time()``) against
    the CV/Andor headers.
    """
    import math
    import time as time_mod
    from types import SimpleNamespace

    from helao.hexagon.app.action_host import ActionHost

    offset_s = 0.138
    frozen_ns = 1_700_000_000_000_000_000

    monkeypatch.setattr(time_mod, "time_ns", lambda: frozen_ns)

    host = SimpleNamespace(
        hexagon_wiring=SimpleNamespace(clock=LegacyClockAdapter(offset_s=offset_s))
    )
    got = ActionHost.get_realtime_nowait(host)
    once = frozen_ns + int(math.floor(offset_s * 1e9))
    twice = frozen_ns + 2 * int(math.floor(offset_s * 1e9))
    assert got == once
    assert got != twice
    # A caller that passes a raw epoch still gets the offset added once.
    assert ActionHost.get_realtime_nowait(host, epoch_ns=frozen_ns) == once
