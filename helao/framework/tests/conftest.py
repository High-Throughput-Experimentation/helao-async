"""Shared pytest fixtures: a fresh fake per port for every test."""
import pytest

from helao.framework.adapters.fakes.clock import FakeClock
from helao.framework.adapters.fakes.eventsink import FakeEventSink
from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.fakes.transport import FakeTransport


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_eventsink() -> FakeEventSink:
    return FakeEventSink()


@pytest.fixture
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def fake_transport() -> FakeTransport:
    return FakeTransport()
