"""A failed hlo->parquet conversion must leave the file pending, not upload ``None``."""

import asyncio
import os
from pathlib import Path

import pytest

import helao.hexagon.adapters.native.sync_driver as native_mod
import helao.core.hooks.builtin.s3_upload as s3_upload_mod
from helao.hexagon.tests.sync_fixtures import (
    make_action,
    make_exp_tree,
    make_sync_driver,
    mk_uuid,
    teardown_driver,
)

HLO = "big-0.0.0.0__0.hlo"


@pytest.mark.asyncio
async def test_failed_parquet_conversion_is_not_uploaded(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("conversion failed")

    monkeypatch.setattr(s3_upload_mod, "hlo_to_parquet", boom)
    drv = make_sync_driver(tmp_path, native_mod.SyncDriver)
    try:
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        big = act_yml.parent / HLO
        big.write_text("x", encoding="utf-8")
        os.truncate(big, 1024**3 + 1)  # sparse: takes the >1GB parquet branch
        act_yml.write_text(
            act_yml.read_text(encoding="utf-8")
            + f"action_status: [finished]\nfiles:\n- file_name: {HLO}\n"
            + "  file_type: helao__file\n",
            encoding="utf-8",
        )
        sent = []

        async def accept(msg=None, target=None, compress=False, retries=5):
            sent.append(msg)
            return True

        drv.to_s3 = accept
        try:
            await asyncio.wait_for(drv.sync_yml(yml_path=act_yml), timeout=15)
        except RuntimeError:
            pass
        assert None not in sent
        prog = native_mod.Progress(act_yml).dict
        assert not prog["files_s3"]
        assert HLO in prog["files_pending"]
    finally:
        await teardown_driver(drv)


@pytest.mark.asyncio
async def test_large_jsonl_converts_to_a_sibling_parquet(tmp_path, monkeypatch):
    """Review Focus 2: ``str(fp).replace(".hlo", ...)`` is a no-op on a .jsonl."""
    calls = []

    def fake(fp, parquet_path, *_a, **_k):
        calls.append((Path(fp), Path(parquet_path)))
        Path(parquet_path).write_bytes(b"PAR1")

    monkeypatch.setattr(s3_upload_mod, "hlo_to_parquet", fake)
    drv = make_sync_driver(tmp_path, native_mod.SyncDriver)
    try:
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        big = act_yml.parent / "big-0.0.0.0__0.jsonl"
        big.write_text("x", encoding="utf-8")
        os.truncate(big, 1024**3 + 1)
        act_yml.write_text(
            act_yml.read_text(encoding="utf-8")
            + "action_status: [finished]\nfiles:\n- file_name: big-0.0.0.0__0.jsonl\n"
            + "  file_type: helao__file\n",
            encoding="utf-8",
        )
        sent = {}

        async def accept(msg=None, target=None, compress=False, retries=5):
            sent[target] = msg
            return True

        drv.to_s3 = accept
        try:
            await asyncio.wait_for(drv.sync_yml(yml_path=act_yml), timeout=15)
        except RuntimeError:
            pass
        parquet = act_yml.parent / "big-0.0.0.0__0.parquet"
        assert calls == [(big, parquet)]
        assert big.stat().st_size == 1024**3 + 1
        assert sent[f"raw_data/{mk_uuid(0)}/big-0.0.0.0__0.parquet"] == parquet
    finally:
        await teardown_driver(drv)
