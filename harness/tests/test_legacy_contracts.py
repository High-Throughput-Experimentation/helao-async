"""§9 contracts pinned against LEGACY: logging path, config identity, clock.

These tests define what the hexagon ports must reproduce (or, for the
tempdir trap, make unreachable). They run on legacy code only — no hexagon
imports exist in P0.
"""

import datetime
import logging as std_logging
import tempfile
from pathlib import Path

from helao.helpers import config_loader
from helao.helpers.config_loader import (
    install_global_config,
    read_config,
    read_validated_config,
)
from helao.helpers.helao_logging import NtpOffsetFormatter, make_logger
from helao.helpers.time_utils import read_saved_offset, set_time


# --- §9.1 logging -----------------------------------------------------------
def test_log_file_lands_at_contract_path(tmp_path, monkeypatch):
    """<root>/LOGS/<server_key>.log — flat file, no per-server subdir.

    DEVIATION FROM BRIEF (pinning real legacy, not intended behavior):
    legacy's ``make_logger`` (helao_logging.py) calls ``tempfile.mkdtemp()``
    *unconditionally* on every invocation as an eager fallback-dir
    allocation, even when ``log_dir`` is supplied and never hits an
    ``OSError``. This is a second, distinct waste trap from the
    ``log_dir=None`` fallback pinned by ``test_tempdir_trap_exists_in_legacy``
    below. The brief's original assertion (``mkdtemp_calls == []``) does not
    match observed legacy behavior, so this test instead pins: mkdtemp IS
    called exactly once regardless, but the resulting log file still lands
    at the caller-supplied path -- never inside the wasted temp dir. The
    hexagon Logging port (P1) must not perform this eager allocation at all.
    """
    mkdtemp_calls = []
    real_mkdtemp = tempfile.mkdtemp

    def spy_mkdtemp(*a, **k):
        d = real_mkdtemp(*a, **k)
        mkdtemp_calls.append(d)
        return d

    monkeypatch.setattr(tempfile, "mkdtemp", spy_mkdtemp)
    log_dir = tmp_path / "LOGS"
    log_dir.mkdir()
    logger = make_logger("GOLDENKEY", log_dir=str(log_dir))
    logger.info("logging path contract check")
    assert (log_dir / "GOLDENKEY.log").exists()
    assert len(mkdtemp_calls) == 1, "legacy eagerly allocates one wasted temp dir"
    assert not any(
        (Path(d) / "GOLDENKEY.log").exists() for d in mkdtemp_calls
    ), "the wasted temp dir must never receive the actual log file"


def test_tempdir_trap_exists_in_legacy(monkeypatch, tmp_path):
    """DOCUMENTS the F3 trap: make_logger(log_dir=None) falls back to mkdtemp.

    The hexagon Logging port must RAISE here instead; when P1 lands, port
    conformance asserts this call path is unreachable through the port.
    """
    made = []

    def fake_mkdtemp(*a, **k):
        d = tmp_path / f"faketmp{len(made)}"
        d.mkdir()
        made.append(str(d))
        return str(d)

    monkeypatch.setattr(tempfile, "mkdtemp", fake_mkdtemp)
    make_logger("TRAPKEY_P0")  # log_dir=None -> legacy silently uses a temp dir
    assert made, "legacy trap fired (expected today; must be dead behind the port)"


def test_logger_handlers_gate_but_logger_is_debug():
    """Logger level min(10, log_level); handlers carry the effective gate."""
    logger = make_logger("LEVELKEY_P0", log_dir=tempfile.mkdtemp(), log_level=30)
    assert logger.level <= 10
    assert logger.propagate is False
    assert any(h.level == 30 for h in logger.handlers)


# --- §9.2 config raw-dict identity -------------------------------------------
def test_config_raw_dict_identity_and_augmentation():
    cfg = read_config("golden")
    installed = install_global_config(cfg)
    assert installed is cfg
    assert config_loader.CONFIG is cfg
    assert config_loader.CONFIG is not None
    # --restore's same-object aliasing gate: the server sub-dict is THE object
    assert config_loader.CONFIG["servers"]["ORCH"] is cfg["servers"]["ORCH"]
    # launcher-added augmentation keys present on the raw dict
    assert "loaded_config_path" in cfg
    assert "helao_repo_root" in cfg


def test_typed_config_is_a_gate_not_a_replacement():
    raw, validated = read_validated_config("golden")
    dumped = validated.model_dump()
    # the schema drops launcher-added keys — installing it would break --restore
    assert "loaded_config_path" in raw
    assert "loaded_config_path" not in dumped


# --- §9.3 clock / NTP ---------------------------------------------------------
def test_offset_file_roundtrip(tmp_path):
    p = tmp_path / "ntpLastSync.txt"
    p.write_text("1752600000.0,2.5")
    last_sync, offset = read_saved_offset(str(p))
    assert last_sync == "1752600000.0"
    assert offset == 2.5


def test_set_time_shifts_by_offset():
    base = set_time(0)
    shifted = set_time(3600.0)
    delta = (shifted - base).total_seconds()
    assert 3599.0 < delta < 3601.0


def test_ntp_formatter_shifts_log_timestamps():
    rec = std_logging.LogRecord("x", 20, "f", 1, "msg", (), None)
    fmt0 = NtpOffsetFormatter("%(asctime)s", offset_seconds=0)
    fmt1 = NtpOffsetFormatter("%(asctime)s", offset_seconds=3600.0)  # type: ignore[arg-type]
    t0 = datetime.datetime.strptime(
        fmt0.formatTime(rec, "%Y-%m-%d %H:%M:%S"), "%Y-%m-%d %H:%M:%S"
    )
    t1 = datetime.datetime.strptime(
        fmt1.formatTime(rec, "%Y-%m-%d %H:%M:%S"), "%Y-%m-%d %H:%M:%S"
    )
    assert abs((t1 - t0).total_seconds() - 3600.0) <= 1.0
