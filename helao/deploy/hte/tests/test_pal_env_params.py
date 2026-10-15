"""PAL SSH identifiers resolve from named env vars, literals still work."""

import logging

from helao.deploy.hte.drivers.robot import pal_driver
from helao.deploy.hte.drivers.robot.pal_driver import _env_param


def test_env_resolution(monkeypatch):
    monkeypatch.setenv("T_PAL_HOST", "example-host")
    assert _env_param({"host_env": "T_PAL_HOST"}, "host", None) == "example-host"


def test_literal_wins_and_fallback_default(monkeypatch):
    monkeypatch.setenv("T_PAL_HOST", "from-env")
    cfg = {"host": "literal", "host_env": "T_PAL_HOST"}
    assert _env_param(cfg, "host", None) == "literal"
    assert _env_param({}, "user", "") == ""
    assert _env_param({}, "host", None) is None


def test_missing_env_logs_error(monkeypatch, caplog):
    monkeypatch.delenv("T_PAL_MISSING", raising=False)
    monkeypatch.setattr(
        pal_driver.LOGGER, "error", lambda m: logging.getLogger("t").error(m)
    )
    with caplog.at_level(logging.ERROR, logger="t"):
        assert _env_param({"host_env": "T_PAL_MISSING"}, "host", None) is None
    assert "T_PAL_MISSING" in caplog.text
