"""Uploading an .hlo must not make the reconciliation warning see a ghost.

Station report (uvis4, 2026-09-28): every synced action with an .hlo logged

    ...\\solid_get_builtin_specref-1.1.0.0__0.hlo.json is named in the files
    list of 1__0__MOTOR__solid_get_builtin_specref but is not on disk

The .hlo.json never exists locally -- it is the S3 key. ``sync_yml`` renames
the uploaded entry in its working ``meta``, and ``meta`` was a shallow copy of
``prog.yml.meta``, so the rename landed in the cached yml meta that
``warn_unregistered_files`` reads afterwards.
"""

import asyncio
import logging

import pytest

import helao.core.drivers.data.sync_driver as legacy_mod
import helao.hexagon.adapters.native.sync_driver as native_mod
from helao.hexagon.tests.sync_fixtures import (
    make_action,
    make_exp_tree,
    make_sync_driver,
    mk_uuid,
    teardown_driver,
)

HLO = "data-0.0.0.0__0.hlo"


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_uploaded_hlo_is_not_reported_missing(tmp_path, mod, monkeypatch, caplog):
    monkeypatch.setattr(mod, "read_hlo", lambda fp: ({}, {}))
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        (act_yml.parent / HLO).write_text("x")
        act_yml.write_text(
            act_yml.read_text()
            + f"action_status: [finished]\nfiles:\n- file_name: {HLO}\n"
            + "  file_type: helao__file\n"
        )

        async def accept(msg=None, target=None, compress=False, retries=5):
            return True

        drv.to_s3 = accept
        caplog.set_level(logging.WARNING)
        await asyncio.wait_for(drv.sync_yml(yml_path=act_yml), timeout=15)
        assert mod.Progress(act_yml).dict["files_s3"], "hlo was not uploaded"
        assert "not on disk" not in caplog.text
        assert "not named in its action's files list" not in caplog.text
    finally:
        await teardown_driver(drv)
