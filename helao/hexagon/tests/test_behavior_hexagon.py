"""§9 cross-cutting behavior contracts asserted on the HEXAGON composition
path (master spec §9.1–9.3; P1 gate). The P0 twins pinning the same
contracts against legacy live in harness/tests/test_legacy_contracts.py."""

import os
import tempfile
from pathlib import Path

import pytest

from helao.helpers import config_loader
from helao.helpers.time_utils import set_time

OFFSET_S = 120.0


def _world(tmp_path):
    return {
        "root": str(tmp_path),
        "dummy": True,
        "simulation": True,
        "servers": {
            "ORCH": {
                "host": "127.0.0.1",
                "port": 8901,
                "group": "orchestrator",
                "fast": "async_orch2",
                "params": {},
            },
            "SIM": {
                "host": "127.0.0.1",
                "port": 8902,
                "group": "action",
                "fast": "ws_simulator",
                "params": {},
            },
        },
    }


@pytest.fixture()
def hex_world(tmp_path, monkeypatch):
    world = _world(tmp_path)
    log_dir = tmp_path / "LOGS"
    log_dir.mkdir()
    (log_dir / "ntpLastSync.txt").write_text(f"1752600000.0,{OFFSET_S}")
    monkeypatch.setattr(config_loader, "CONFIG", world)
    return world


# --- §9.1 logging: contractual path, tempdir traps dead behind the port -----
def test_s9_1_composition_log_file_lands_under_root_logs(hex_world, monkeypatch):
    from helao.hexagon.app.factory import build_wiring

    mkdtemp_dirs = []
    real_mkdtemp = tempfile.mkdtemp

    def spy_mkdtemp(*a, **k):
        d = real_mkdtemp(*a, **k)
        mkdtemp_dirs.append(d)
        return d

    monkeypatch.setattr(tempfile, "mkdtemp", spy_mkdtemp)
    w = build_wiring("ORCH")
    assert w.logging is not None
    log_root = os.path.join(hex_world["root"], "LOGS")
    lg = w.logging.file_logger("HEXBEH", log_root)
    lg.info("hexagon §9.1 behavior check")  # type: ignore[attr-defined]
    assert (Path(log_root) / "HEXBEH.log").exists()  # flat file, no subdir
    assert not any(
        (Path(d) / "HEXBEH.log").exists() for d in mkdtemp_dirs
    ), "log file must never land in a temp dir"
    # no parallel LOGS_FW-style directory, ever (§9.1 rule 2)
    assert not (Path(hex_world["root"]) / "LOGS_FW").exists()


def test_s9_1_composition_port_refuses_unresolved_log_root(hex_world):
    from helao.hexagon.app.factory import build_wiring

    w = build_wiring("ORCH")
    assert w.logging is not None
    with pytest.raises(ValueError):
        w.logging.file_logger("HEXBEH", None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        w.logging.file_logger("HEXBEH", "")


# --- §9.2 config: raw-dict identity through the composition ------------------
def test_s9_2_config_identity_and_restore_aliasing(hex_world):
    from helao.hexagon.app.factory import build_wiring

    w = build_wiring("ORCH")
    assert w.config is not None
    # the port hands out views of THE installed dict object
    assert w.config.world_cfg() is config_loader.CONFIG
    assert w.config.world_cfg() is hex_world
    # --restore's same-object aliasing gate: server sub-dict IS the object
    assert w.config.server_cfg("ORCH") is hex_world["servers"]["ORCH"]
    # mutation through the raw dict is visible through the port (no copies)
    hex_world["servers"]["ORCH"]["params"]["marker"] = 1
    assert w.config.server_cfg("ORCH")["params"]["marker"] == 1


# --- §9.3 clock: offset file drives every minted timestamp -------------------
def test_s9_3_clock_offset_file_shifts_composition_time(hex_world):
    from helao.hexagon.app.factory import build_wiring

    w = build_wiring("ORCH")
    assert w.clock is not None
    assert w.clock.offset() == OFFSET_S
    delta = (w.clock.now() - set_time(0)).total_seconds()
    assert OFFSET_S - 2.0 < delta < OFFSET_S + 2.0


def test_s9_3_clock_missing_offset_file_is_zero(tmp_path, monkeypatch):
    world = _world(tmp_path)
    (tmp_path / "LOGS").mkdir()  # no ntpLastSync.txt
    monkeypatch.setattr(config_loader, "CONFIG", world)
    from helao.hexagon.app.factory import build_wiring

    w = build_wiring("ORCH")
    assert w.clock is not None
    assert w.clock.offset() == 0.0
