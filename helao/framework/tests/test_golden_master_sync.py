"""End-to-end golden-master parity test for the SP6 data-sync pipeline.

HOW THIS GOLDEN MASTER WAS PRODUCED
-----------------------------------
Driving the legacy ``helao.core.drivers.data.sync_driver.HelaoSyncer`` in-process
is impractical: it is coupled to ``boto3``/AWS bootstrapping (``load_aws_config``,
a live S3 client), an API host for ``to_api``, and a ``Base`` server for its
loggers and config. Standing all of that up in a unit test would test the
harness, not the *pipeline semantics*.

Instead -- exactly as ``test_golden_master_action.py`` and
``test_golden_master_orchestration.py`` do -- this test:

* commits a small but REALISTIC ``RUNS_FINISHED`` tree fixture
  (``fixtures/sync/RUNS_FINISHED/...``) in the byte-faithful legacy on-disk
  layout: ``<runs>/<week>/<date>/<seq_dir>/<exp_dir>/<act_dir>/<ts>-{seq,exp,act}.yml``
  with the UUID carried in the YAML body and the record timestamp in the
  filename. The action dir carries one ``.hlo`` data file plus one misc file.
* copies that fixture into pytest ``tmp_path`` and drives the *real* framework
  pipeline through the real :class:`FsSyncStorage` filesystem adapter, with a
  :class:`NoopCloudSink` so NO S3/network is touched -- the file move + zip are
  real, only the (cloud) egress is stubbed. The sync is driven bottom-up
  (action, then experiment, then sequence) because a parent only PROCEEDs once
  all its children live under ``RUNS_SYNCED`` (legacy child-status gate, see
  ``decide.decide_sync``).
* asserts the resulting on-disk state against an inline GOLDEN expectation,
  each clause citing the legacy ``sync_driver.py`` line range it derives from.
  The legacy syncer is NOT run here; the citation is the parity contract. If the
  framework move/zip/prg logic drifts, these assertions fail loud.

LEGACY LINE CITATIONS  (into ``helao/core/drivers/data/sync_driver.py``)
-----------------------------------------------------------------------
* ``move_to_synced`` (FINISHED->SYNCED string-replace + shutil.move) -- 97-126.
* the ``.prg`` default schema (``yml``/``api``/``s3`` + per-type fields) -- 569-591.
* ``sync_yml`` PROCEED body: upload files, patch+push yml doc, register api,
  then move hlo+misc+yml to synced, then (seq only) zip the synced dir -- the
  framework analogue lives in ``app/sync_driver.SyncDriver.sync_yml``; the legacy
  move/zip block is 1262-1349 and the per-file upload loop is 1108-1206.

WHAT THIS COVERS / OMITS
------------------------
COVERS, end-to-end through real fs:
  - the full seq->exp->act chain relocated FINISHED -> SYNCED at the correct
    relative paths (meta ymls + the .hlo + the misc file all move);
  - the sequence dir is zipped under RUNS_SYNCED (``<name>.zip`` sibling) and the
    source tree removed;
  - each node's ``.prg`` sidecar exists with the legacy schema and both
    ``s3``/``api`` legs marked done.
OMITS (deliberate, out of scope for a NoopCloudSink fs golden master):
  - real S3 object bytes / real API registration payloads (NoopCloudSink stubs
    both -- covered by ``test_app_sync_driver`` against the recording fake).
PROCESS FOLDING is exercised: the fixture action carries ``process_contrib`` and
the experiment a ``process_order_groups`` group, so the action sync runs
``update_process`` -> ``sync_process`` and the experiment ``.prg`` accumulates
``process_metas``/``process_s3`` (asserted below). This guards the
Progress-threading bugs that a ``process_contrib: false`` fixture could not.
"""
from __future__ import annotations

import asyncio
import shutil
import zipfile
from pathlib import Path

from helao.framework.adapters.fs_sync_storage import FsSyncStorage
from helao.framework.adapters.noop_cloud_sink import NoopCloudSink
from helao.framework.app.sync_driver import SyncDriver
from helao.framework.support.yml_tools import yml_load

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sync"

WEEK_DATE = "26.25/0622"
SEQ_DIR = "240622.120000000000__demo_seq"
EXP_DIR = "240622.120001000000__demo_exp"
ACT_DIR = "240622.120002000000__0__act__measure"

SEQ_YML = "240622.120000000000-seq.yml"
EXP_YML = "240622.120001000000-exp.yml"
ACT_YML = "240622.120002000000-act.yml"


def _copy_fixture(tmp_path: Path) -> Path:
    """Copy the committed RUNS_FINISHED fixture tree into ``tmp_path``; return root."""
    root = tmp_path / "INST_hlo"
    shutil.copytree(FIXTURE_ROOT, root)
    assert (root / "RUNS_FINISHED").is_dir(), "fixture missing RUNS_FINISHED tree"
    return root


def _finished(root: Path) -> Path:
    return root / "RUNS_FINISHED" / WEEK_DATE


def _synced(root: Path) -> Path:
    return root / "RUNS_SYNCED" / WEEK_DATE


def _new_driver():
    return SyncDriver(
        FsSyncStorage(), NoopCloudSink(), {"aws_bucket": "golden-bucket"}, max_tasks=1
    )


def _drive_children(root: Path) -> None:
    """Sync only action + experiment (NOT the sequence, so its dir stays loose).

    The sequence sync is what zips and removes the whole synced sequence tree, so
    to inspect the relocated child files loose on disk we stop before it. Actions
    sync before parents (legacy child-status gate: a parent only PROCEEDs once
    every child lives under RUNS_SYNCED).
    """
    driver = _new_driver()
    fin = _finished(root)
    act_yml = fin / SEQ_DIR / EXP_DIR / ACT_DIR / ACT_YML
    exp_yml = fin / SEQ_DIR / EXP_DIR / EXP_YML

    async def _go():
        await driver.sync_yml(act_yml)
        await driver.sync_yml(exp_yml)

    asyncio.run(_go())


def _drive_full_sync(root: Path) -> None:
    """Drive the real pipeline bottom-up: action -> experiment -> sequence.

    The final sequence sync zips the whole synced sequence dir into
    ``<SEQ_DIR>.zip`` and removes the loose tree (legacy seq move+zip 1262-1349).
    """
    driver = _new_driver()
    fin = _finished(root)
    act_yml = fin / SEQ_DIR / EXP_DIR / ACT_DIR / ACT_YML
    exp_yml = fin / SEQ_DIR / EXP_DIR / EXP_YML
    seq_yml = fin / SEQ_DIR / SEQ_YML

    async def _go():
        await driver.sync_yml(act_yml)
        await driver.sync_yml(exp_yml)
        await driver.sync_yml(seq_yml)

    asyncio.run(_go())


# --------------------------------------------------------------------------- #
# the golden master
# --------------------------------------------------------------------------- #


def test_children_relocate_finished_to_synced(tmp_path):
    root = _copy_fixture(tmp_path)
    _drive_children(root)  # action + experiment only (no seq zip yet)

    syn = _synced(root)

    # --- the exp + act meta ymls relocated to RUNS_SYNCED at the same relative
    # paths (legacy move_to_synced 97-126: FINISHED->SYNCED string replace + move)
    assert (syn / SEQ_DIR / EXP_DIR / EXP_YML).exists()
    assert (syn / SEQ_DIR / EXP_DIR / ACT_DIR / ACT_YML).exists()

    # --- the action's data files relocated too (hlo + misc) ---
    # (legacy sync_yml move block 1262-1349 moves hlo_files + misc_files + yml)
    act_synced = syn / SEQ_DIR / EXP_DIR / ACT_DIR
    assert (act_synced / "measure.hlo").exists()
    assert (act_synced / "aux_readme.txt").exists()

    # --- the action + experiment moved out of RUNS_FINISHED (move, not copy) ---
    # the seq yml is NOT yet synced here, so it remains under RUNS_FINISHED.
    assert list(_finished(root).rglob("*-act.yml")) == []
    assert list(_finished(root).rglob("*-exp.yml")) == []
    assert (_finished(root) / SEQ_DIR / SEQ_YML).exists()


def test_full_chain_drains_finished_to_synced(tmp_path):
    root = _copy_fixture(tmp_path)
    _drive_full_sync(root)

    # after the sequence syncs, its whole synced tree is zipped + removed, so
    # nothing for this run remains under RUNS_FINISHED (move, not copy).
    fin = _finished(root)
    leftover = list(fin.rglob("*-seq.yml"))
    leftover += list(fin.rglob("*-exp.yml"))
    leftover += list(fin.rglob("*-act.yml"))
    assert leftover == [], f"unsynced leftovers under RUNS_FINISHED: {leftover}"
    assert list(fin.rglob("*.hlo")) == []
    # The .prg sidecar lives under RUNS_SYNCED (legacy line 557:
    # yml.synced_path.with_suffix(".prg")), NEVER orphaned in RUNS_FINISHED.
    assert list(fin.rglob("*.prg")) == [], (
        f"orphan .prg left under RUNS_FINISHED: {list(fin.rglob('*.prg'))}"
    )


def test_sequence_dir_is_zipped_under_synced(tmp_path):
    root = _copy_fixture(tmp_path)
    _drive_full_sync(root)

    syn = _synced(root)
    # legacy zips the synced sequence dir as a sibling <name>.zip and removes the
    # source tree (app/sync_driver.sync_yml seq branch -> FsSyncStorage.zip_dir).
    seq_zip = syn / f"{SEQ_DIR}.zip"
    assert seq_zip.exists(), f"sequence dir not zipped; expected {seq_zip}"

    # the loose source tree is removed by zip_dir; the only loose artifact left is
    # the seq .prg, which sync_yml re-writes to the moved target AFTER zipping
    # (app/sync_driver step 6: zip, then _write_progress(new_yml)). No meta yml or
    # data file should remain loose under the synced seq dir.
    loose = [p for p in (syn / SEQ_DIR).rglob("*") if p.is_file()] if (syn / SEQ_DIR).exists() else []
    loose_non_prg = [p for p in loose if p.suffix != ".prg"]
    assert loose_non_prg == [], f"unexpected loose files after seq zip: {loose_non_prg}"

    # the zip carries the relocated meta + data files (whole synced seq subtree).
    with zipfile.ZipFile(seq_zip) as zf:
        names = "\n".join(zf.namelist())
    assert SEQ_YML in names
    assert EXP_YML in names
    assert ACT_YML in names
    assert "measure.hlo" in names
    assert "aux_readme.txt" in names


def test_prg_sidecars_have_legacy_schema_with_both_legs_done(tmp_path):
    root = _copy_fixture(tmp_path)
    _drive_children(root)  # leave act/exp loose so their .prg can be read directly

    syn = _synced(root)

    # The action + experiment .prg sidecars live next to their synced ymls.
    # (legacy .prg default schema 569-591; both legs flipped True on a completed
    # PROCEED -- app/sync_driver steps 4-5.)
    act_prg = yml_load(syn / SEQ_DIR / EXP_DIR / ACT_DIR / ACT_YML.replace(".yml", ".prg"))
    exp_prg = yml_load(syn / SEQ_DIR / EXP_DIR / EXP_YML.replace(".yml", ".prg"))

    # base keys present on every node (legacy 569-573)
    for prg in (act_prg, exp_prg):
        assert set(["yml", "api", "s3"]).issubset(prg.keys())
        assert prg["s3"] is True, f"s3 leg not done: {prg}"
        assert prg["api"] is True, f"api leg not done: {prg}"
        # the prg's yml target was rewritten to the RUNS_SYNCED path on move.
        assert "RUNS_SYNCED" in str(prg["yml"])

    # action-only fields present in the schema (legacy 574-579).
    assert "files_pending" in act_prg and "files_s3" in act_prg
    # A completed action PROCEED leaves NOTHING pending and records every
    # uploaded file in files_s3. The fixture action carries one .hlo + one misc
    # file, so files_s3 has two entries. (This is the CRITICAL-1 parity contract:
    # _upload_action_files returns a NEW Progress that sync_yml MUST rebind and
    # persist -- legacy accumulates the per-file map in the one prg dict,
    # 1160-1180/1287.)
    assert act_prg["files_pending"] == []
    assert len(act_prg["files_s3"]) == 2, f"files_s3 not threaded into prg: {act_prg}"

    # experiment-only fields (legacy 580-591)
    for key in (
        "process_actions_done",
        "process_groups",
        "process_metas",
        "process_s3",
        "process_api",
        "legacy_finisher_idxs",
        "legacy_experiment",
    ):
        assert key in exp_prg, f"experiment prg missing legacy field {key}"

    # CRITICAL-2 parity contract: the action's update_process -> sync_process
    # folds the contributing action into the experiment process bookkeeping and
    # pushes it. The advanced experiment Progress MUST round-trip to the exp prg
    # under RUNS_SYNCED (the fixture exp has process_order_groups {0:[0]} and the
    # action sets process_contrib + process_finish). A dropped _finalize_processes
    # return would leave these empty.
    assert exp_prg["legacy_experiment"] is False, "modern experiment expected"
    assert 0 in exp_prg["process_actions_done"], (
        f"action not recorded into process_actions_done: {exp_prg}"
    )
    assert exp_prg["process_metas"], f"process_metas not folded: {exp_prg}"
    assert 0 in exp_prg["process_s3"], f"process not pushed to s3: {exp_prg}"

    # The sequence .prg ends up inside the zip (its dir is zipped after the seq
    # syncs), so drive a full sync on a fresh fixture and assert it is present in
    # the archive rather than loose on disk.
    root2 = _copy_fixture(tmp_path / "full")
    _drive_full_sync(root2)
    seq_zip = _synced(root2) / f"{SEQ_DIR}.zip"
    with zipfile.ZipFile(seq_zip) as zf:
        assert any(n.endswith(SEQ_YML.replace(".yml", ".prg")) for n in zf.namelist()), (
            "sequence .prg sidecar missing from zipped synced dir"
        )
