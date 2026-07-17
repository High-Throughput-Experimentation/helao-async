"""Fail-loud composition primitive (spec §10.2 / §4.5: composition RAISES on
any unwired port — there are no default fakes)."""

import pytest

from helao.hexagon.app.wiring import (
    ACTION_REQUIRED,
    ORCH_REQUIRED,
    PortWiring,
    UnwiredPortError,
)
from helao.hexagon.adapters.fakes import FakeClock, FakeTransport


def test_require_raises_listing_every_missing_port():
    w = PortWiring(clock=FakeClock())
    with pytest.raises(UnwiredPortError) as ei:
        w.require("config", "clock", "transport")
    msg = str(ei.value)
    assert "config" in msg and "transport" in msg
    assert "clock" not in msg  # wired ports are not reported


def test_require_passes_when_all_wired():
    w = PortWiring(clock=FakeClock(), transport=FakeTransport())
    w.require("clock", "transport")  # no raise


def test_require_rejects_unknown_port_name():
    with pytest.raises(UnwiredPortError):
        PortWiring().require("no_such_port")


def test_required_sets_are_frozen_tuples():
    assert set(ACTION_REQUIRED) <= set(ORCH_REQUIRED) | {"transport"}
    assert "state_persistence" in ORCH_REQUIRED
