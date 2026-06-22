import pytest

from helao.framework.ports.storage import Storage, StorageKeyError
from helao.framework.adapters.fakes.storage import FakeStorage


def test_fake_satisfies_protocol():
    storage: Storage = FakeStorage()
    assert isinstance(storage, Storage)


def test_write_returns_relpath_and_read_roundtrips():
    storage = FakeStorage()
    written = storage.write_json("runs/act/meta.json", {"a": 1, "b": [2, 3]})
    assert written == "runs/act/meta.json"
    assert storage.read_json("runs/act/meta.json") == {"a": 1, "b": [2, 3]}


def test_write_snapshots_payload():
    storage = FakeStorage()
    payload = {"n": 1}
    storage.write_json("x.json", payload)
    payload["n"] = 999
    assert storage.read_json("x.json") == {"n": 1}


def test_read_missing_raises_storagekeyerror():
    storage = FakeStorage()
    with pytest.raises(StorageKeyError):
        storage.read_json("nope.json")
