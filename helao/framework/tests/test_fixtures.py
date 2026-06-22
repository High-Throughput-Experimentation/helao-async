from helao.framework.adapters.fakes.clock import FakeClock
from helao.framework.adapters.fakes.eventsink import FakeEventSink
from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.fakes.transport import FakeTransport


def test_fixtures_provide_fresh_fakes(fake_clock, fake_eventsink, fake_storage, fake_transport):
    assert isinstance(fake_clock, FakeClock)
    assert isinstance(fake_eventsink, FakeEventSink)
    assert isinstance(fake_storage, FakeStorage)
    assert isinstance(fake_transport, FakeTransport)


def test_fake_storage_fixture_is_isolated_between_tests(fake_storage):
    # If this fixture leaked state from another test, this key would exist.
    from helao.framework.ports.storage import StorageKeyError
    import pytest
    with pytest.raises(StorageKeyError):
        fake_storage.read_json("leaked.json")
