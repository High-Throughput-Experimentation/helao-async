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


# --- extended HLO / meta / relocate / postproc surface ---


@pytest.mark.asyncio
async def test_open_hlo_records_header_and_separator():
    storage = FakeStorage()
    handle = await storage.open_hlo("runs/a/data.hlo", "hlo_version: 1.0")
    assert storage.hlo_buffers["runs/a/data.hlo"] == "hlo_version: 1.0\n%%\n"
    assert handle.closed is False


@pytest.mark.asyncio
async def test_open_append_close_builds_full_hlo_buffer():
    storage = FakeStorage()
    handle = await storage.open_hlo("d.hlo", "k: v")
    await storage.append_hlo(handle, '{"t": 1}')
    await storage.append_hlo(handle, '{"t": 2}\n')  # already newline-terminated
    await storage.close_hlo(handle)
    assert storage.hlo_buffers["d.hlo"] == 'k: v\n%%\n{"t": 1}\n{"t": 2}\n'
    assert handle.closed is True


@pytest.mark.asyncio
async def test_open_hlo_empty_header_is_just_separator():
    storage = FakeStorage()
    await storage.open_hlo("d.hlo", "")
    assert storage.hlo_buffers["d.hlo"] == "%%\n"


@pytest.mark.asyncio
async def test_write_meta_records_doc_and_snapshots():
    storage = FakeStorage()
    doc = {"file_type": "action", "n": 1}
    returned = await storage.write_meta("runs/a/x-act.yml", doc)
    assert returned == "runs/a/x-act.yml"
    doc["n"] = 999
    assert storage.meta_docs["runs/a/x-act.yml"] == {"file_type": "action", "n": 1}


@pytest.mark.asyncio
async def test_relocate_records_src_dst():
    storage = FakeStorage()
    dst = await storage.relocate("/tmp/in/a.csv", "runs/a/a.csv")
    assert dst == "runs/a/a.csv"
    assert storage.relocations == [("/tmp/in/a.csv", "runs/a/a.csv")]


@pytest.mark.asyncio
async def test_run_postprocessor_records_call_and_returns_files():
    storage = FakeStorage()
    out = await storage.run_postprocessor(
        "proc", "runs/a/data.hlo", {"files": [{"file_name": "data.hlo"}]}
    )
    assert out == [{"file_name": "data.hlo"}]
    assert storage.postproc_calls[0][0] == "proc"
    assert storage.postproc_calls[0][1] == "runs/a/data.hlo"
