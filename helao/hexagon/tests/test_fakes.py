"""Fakes must satisfy their Protocols and record faithfully."""

import asyncio
from datetime import datetime

from helao.hexagon.adapters import fakes
from helao.hexagon.domain.models import Action, ErrorCodes
from helao.hexagon.ports.clock import ClockPort
from helao.hexagon.ports.status import StatusPort
from helao.hexagon.ports.transport import TransportPort


def test_fakes_satisfy_protocols():
    assert isinstance(fakes.FakeClock(), ClockPort)
    assert isinstance(fakes.FakeTransport(), TransportPort)
    assert isinstance(fakes.FakeStatusPush(), StatusPort)


def test_fake_clock_is_deterministic():
    clk = fakes.FakeClock(fixed=datetime(2026, 7, 17, 12, 0, 0), offset_s=1.5)
    assert clk.now() == datetime(2026, 7, 17, 12, 0, 0)
    assert clk.offset() == 1.5
    assert clk.now_ns() == int(datetime(2026, 7, 17, 12, 0, 0).timestamp() * 1e9)


def test_fake_transport_records_dispatches():
    tr = fakes.FakeTransport()
    act = Action(action_name="acquire")
    act.action_server.server_name = "SIM"
    resp, err = asyncio.run(tr.dispatch_action(act))
    assert err == ErrorCodes.none
    assert len(tr.dispatched) == 1
    method, payload = tr.dispatched[0]
    assert method == "SIM/acquire"
    assert payload["action"]["action_name"] == "acquire"


def test_fake_transport_scripted_failure():
    tr = fakes.FakeTransport(fail_with=ErrorCodes.http)
    act = Action(action_name="acquire")
    act.action_server.server_name = "SIM"
    resp, err = asyncio.run(tr.dispatch_action(act))
    assert resp is None and err == ErrorCodes.http
