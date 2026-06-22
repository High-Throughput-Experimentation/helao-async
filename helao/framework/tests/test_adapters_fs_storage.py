"""Byte-format tests for the real filesystem Storage adapter.

Asserts the on-disk HLO layout matches legacy ``helao.core.servers.base``:
``[HEADER]\\n%%\\n[JSON ROW]\\n...``; atomic meta round-trips; relocate copies.
"""
import json
import os

import pytest

from helao.framework.ports.storage import Storage, StorageKeyError
from helao.framework.adapters.fs_storage import FsStorage


def test_fs_satisfies_protocol(tmp_path):
    storage: Storage = FsStorage(str(tmp_path))
    assert isinstance(storage, Storage)


@pytest.mark.asyncio
async def test_hlo_bytes_are_legacy_identical(tmp_path):
    storage = FsStorage(str(tmp_path))
    header = "hlo_version: 1.0\naction_name: dummy\ncolumn_headings:\n    - t\n    - v"
    rows = ['{"t": 0.0, "v": 1.5}', '{"t": 0.1, "v": 2.5}']

    handle = await storage.open_hlo("runs/act/data.hlo", header)
    for r in rows:
        await storage.append_hlo(handle, r)
    await storage.close_hlo(handle)

    on_disk = (tmp_path / "runs" / "act" / "data.hlo").read_bytes()
    expected = (
        header
        + "\n%%\n"
        + '{"t": 0.0, "v": 1.5}\n'
        + '{"t": 0.1, "v": 2.5}\n'
    ).encode("utf-8")
    assert on_disk == expected


@pytest.mark.asyncio
async def test_open_hlo_empty_header_writes_only_separator(tmp_path):
    storage = FsStorage(str(tmp_path))
    handle = await storage.open_hlo("d.hlo", "")
    await storage.close_hlo(handle)
    assert (tmp_path / "d.hlo").read_bytes() == b"%%\n"


@pytest.mark.asyncio
async def test_write_meta_atomic_no_tmp_left_and_roundtrips(tmp_path):
    storage = FsStorage(str(tmp_path))
    doc = {"file_type": "action", "action_name": "dummy", "nested": {"a": 1}}
    relpath = "runs/act/250101.120000123456-act.yml"
    returned = await storage.write_meta(relpath, doc)
    assert returned == relpath

    out_file = tmp_path / "runs" / "act" / "250101.120000123456-act.yml"
    text = out_file.read_text()
    assert text.endswith("\n")
    assert text.startswith("file_type: action")

    # no temp files left in the directory
    leftovers = [p.name for p in out_file.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []

    # round-trips back to the same doc
    from helao.helpers.yml_tools import yml_load

    assert dict(yml_load(text)) == doc


@pytest.mark.asyncio
async def test_relocate_copies_file(tmp_path):
    storage = FsStorage(str(tmp_path))
    src = tmp_path / "incoming" / "aux.csv"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"col\n1\n2\n")

    dst = await storage.relocate(str(src), "runs/act/aux.csv")
    assert dst == "runs/act/aux.csv"
    copied = tmp_path / "runs" / "act" / "aux.csv"
    assert copied.read_bytes() == b"col\n1\n2\n"
    # source still present (copy, not move)
    assert src.exists()


@pytest.mark.asyncio
async def test_run_postprocessor_returns_context_files(tmp_path):
    storage = FsStorage(str(tmp_path))
    files = [{"file_name": "data.hlo"}]
    out = await storage.run_postprocessor("noop", "runs/act/data.hlo", {"files": files})
    assert list(out) == files


def test_write_json_read_json_roundtrip(tmp_path):
    storage = FsStorage(str(tmp_path))
    storage.write_json("runs/x.json", {"a": 1, "b": [2, 3]})
    assert storage.read_json("runs/x.json") == {"a": 1, "b": [2, 3]}


def test_read_json_missing_raises(tmp_path):
    storage = FsStorage(str(tmp_path))
    with pytest.raises(StorageKeyError):
        storage.read_json("nope.json")
