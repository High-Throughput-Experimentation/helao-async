"""P2c D3 gate: direct-drive on-tree parity, legacy vs native SyncDriver.

Input: a pre-sync RUNS_FINISHED tree reconstructed from the GM-1 golden via
the LEGACY reset_sync (the goldens are post-sync; reset_sync is the
pipeline's own reversal, proven by the GM-5 flow). Both drivers consume
byte-identical copies of that tree with a RecordingS3Client; outputs are
compared with harness.parity.run_parity — THE golden gate comparator —
asserting 0 diffs across RUNS_SYNCED zip members, PROCESSES -prc.yml,
S3_SIM payloads, and manifest.jsonl (internal_s3_checks additionally
asserts the 2 intentional S3-vs-disk quirks on BOTH outputs). The
round-trip test then reset_syncs + finish_pendings BOTH outputs again
(GM-5 analog) and re-asserts 0 diffs.

CONTROLLER F1 additions (strengthen the gate beyond legacy-vs-native, which
is tautological since both drivers are byte-identical bodies):
- F1a: compares a re-driven tree (native and legacy) against the immutable
  committed GOLDEN itself, not just against each other.
- F1b: drives one side through NativeSyncAdapter (not the raw driver), to
  exercise the adapter's delegation surface in the gate."""

import glob as globmod
import json
import os
import shutil
from pathlib import Path

import pytest

from harness.parity import run_parity
from helao.core.drivers.data.sync_driver import SyncDriver as LegacySyncDriver
from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir
from helao.deploy.test.servers.action.sim_db_server import RecordingS3Client
from helao.hexagon.adapters.native.sync_adapter import NativeSyncAdapter
from helao.hexagon.adapters.native.sync_driver import SyncDriver as NativeSyncDriver
from helao.hexagon.tests.sync_fixtures import drain, teardown_driver

GOLDEN = (
    Path(os.environ.get("HELAO_GOLDENS", "/home/dan/helao_goldens")) / "GM-1" / "run1"
)
BUCKET = "helao.data"  # matches the GM-1 capture's S3_SIM/<bucket> layout
CFG = {"aws_bucket": BUCKET, "max_tasks": 1}

pytestmark = pytest.mark.skipif(
    not GOLDEN.is_dir(), reason=f"GM-1 golden set not found at {GOLDEN}"
)
# NOTE: T12 verifies this module ran (0 skipped) — a silent skip guts the gate.


@pytest.fixture(autouse=True)
def _hermetic_aws(monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)


def _hd(root: Path) -> HelaoDirs:
    return HelaoDirs(
        root=root,
        save_root=root / RunDir.ACTIVE.value,
        process_root=root / "PROCESSES",
    )


async def _reconstruct_input(tmp_path: Path) -> Path:
    """Golden post-sync root -> pre-sync RUNS_FINISHED tree (legacy reset_sync)."""
    stage = tmp_path / "stage"
    shutil.copytree(GOLDEN / "root", stage)
    zips = globmod.glob(
        str(stage / RunDir.SYNCED.value / "**" / "*.zip"), recursive=True
    )
    assert len(zips) == 1, f"expected exactly one synced sequence zip, got {zips}"
    prep = LegacySyncDriver(CFG, _hd(stage))
    try:
        assert prep.reset_sync(zips[0]) is True
    finally:
        await teardown_driver(prep)
    for top in (RunDir.SYNCED.value, "PROCESSES", "S3_SIM", "ANALYSES", "RUNS_NOSYNC"):
        shutil.rmtree(stage / top, ignore_errors=True)
    seqs = globmod.glob(
        str(stage / RunDir.FINISHED.value / "**" / "*-seq.yml"), recursive=True
    )
    assert len(seqs) == 1, "reconstruction must yield exactly one pending sequence"
    return stage


async def _drive(root: Path, driver_cls) -> None:
    drv = driver_cls(CFG, _hd(root))
    drv.s3 = RecordingS3Client(root / "S3_SIM")
    try:
        await drv.finish_pending()
        await drain(drv, timeout=180.0)
    finally:
        await teardown_driver(drv)
    leftovers = globmod.glob(
        str(root / RunDir.FINISHED.value / "**" / "*.yml"), recursive=True
    )
    assert (
        leftovers == []
    ), f"{driver_cls.__module__}: unsynced ymls remain: {leftovers}"


def _assert_zero_diffs(legacy_set: Path, native_root: Path, tag: str) -> None:
    report = run_parity(legacy_set, native_root)
    assert report["status"] == "pass" and report["n_diffs"] == 0, (
        f"[{tag}] legacy-vs-native sync parity failed "
        f"(run {report['run_id']}):\n{json.dumps(report, indent=2, default=str)}"
    )


async def _prepare_both_sides(tmp_path: Path):
    stage = await _reconstruct_input(tmp_path)
    legacy_set = tmp_path / "legacy_set"
    legacy_set.mkdir()
    shutil.copytree(stage, legacy_set / "root")
    shutil.copy(GOLDEN / "provenance.yml", legacy_set / "provenance.yml")
    native_root = tmp_path / "native_root"
    shutil.copytree(stage, native_root)
    await _drive(legacy_set / "root", LegacySyncDriver)
    await _drive(native_root, NativeSyncDriver)
    return legacy_set, native_root


@pytest.mark.asyncio
async def test_direct_drive_tree_parity(tmp_path):
    legacy_set, native_root = await _prepare_both_sides(tmp_path)
    _assert_zero_diffs(legacy_set, native_root, "full-sync")

    # --- F1a: non-tautological immutable-golden check --------------------
    # The legacy-vs-native compare above is tautological (byte-identical
    # driver bodies trivially match). Additionally compare each re-driven
    # side against the immutable committed GOLDEN itself. reset_sync then
    # re-sync is not guaranteed to be a perfect identity under the
    # comparator, so gate the strong assertion on whether legacy itself
    # round-trips clean against the golden.
    legacy_vs_golden = run_parity(GOLDEN, legacy_set / "root")
    native_vs_golden = run_parity(GOLDEN, native_root)
    if legacy_vs_golden["n_diffs"] == 0:
        # Reconstruction is a clean round-trip -> native must reproduce the
        # immutable golden bytes exactly. This is the strong, non-tautological
        # gate: native output == the real captured GM-1 run, not just == a
        # freshly-run legacy sibling.
        assert native_vs_golden["n_diffs"] == 0, (
            "[golden] native failed to reproduce immutable GM-1 golden bytes "
            f"(run {native_vs_golden['run_id']}):\n"
            f"{json.dumps(native_vs_golden, indent=2, default=str)}"
        )
    else:
        # reset_sync -> finish_pending round-trip is not a perfect identity
        # under the comparator (legacy itself diverges from the golden), so
        # the golden compare is artifact-bounded and can't cleanly isolate
        # native drift on its own. The primary byte-parity gate is the
        # legacy-vs-native 0-diff assertion above; here we additionally
        # require native to diverge from the golden by EXACTLY the same
        # amount as legacy does (no additional native-introduced drift).
        assert native_vs_golden["n_diffs"] == legacy_vs_golden["n_diffs"], (
            "[golden] native introduced additional drift vs golden beyond "
            "legacy's own reset-round-trip artifacts "
            f"(legacy={legacy_vs_golden['n_diffs']} diffs, "
            f"native={native_vs_golden['n_diffs']} diffs):\n"
            f"legacy_vs_golden={json.dumps(legacy_vs_golden, indent=2, default=str)}\n"
            f"native_vs_golden={json.dumps(native_vs_golden, indent=2, default=str)}"
        )


@pytest.mark.asyncio
async def test_reset_and_finish_pending_round_trip(tmp_path):
    """GM-5 analog: reset the synced output on BOTH sides with each side's own
    driver, re-sync via finish_pending, and re-assert 0 diffs (.orig included
    — explode_zips normalizes it into .origdir on both sides)."""
    legacy_set, native_root = await _prepare_both_sides(tmp_path)
    for root, driver_cls in (
        (legacy_set / "root", LegacySyncDriver),
        (native_root, NativeSyncDriver),
    ):
        zips = globmod.glob(
            str(root / RunDir.SYNCED.value / "**" / "*.zip"), recursive=True
        )
        assert len(zips) == 1
        drv = driver_cls(CFG, _hd(root))
        drv.s3 = RecordingS3Client(root / "S3_SIM")
        try:
            assert drv.reset_sync(zips[0]) is True
            assert Path(zips[0].replace(".zip", ".orig")).exists()
            await drv.finish_pending()
            await drain(drv, timeout=180.0)
        finally:
            await teardown_driver(drv)
    _assert_zero_diffs(legacy_set, native_root, "round-trip")


@pytest.mark.asyncio
async def test_native_sync_adapter_drives_parity(tmp_path):
    """F1b: exercise NativeSyncAdapter's delegation surface (not just the raw
    NativeSyncDriver) in the gate. One side is driven through the adapter,
    the other through the raw legacy driver; outputs must still show 0
    diffs under run_parity."""
    stage = await _reconstruct_input(tmp_path)
    legacy_set = tmp_path / "legacy_set"
    legacy_set.mkdir()
    shutil.copytree(stage, legacy_set / "root")
    shutil.copy(GOLDEN / "provenance.yml", legacy_set / "provenance.yml")
    native_root = tmp_path / "native_root"
    shutil.copytree(stage, native_root)

    await _drive(legacy_set / "root", LegacySyncDriver)

    adapter = NativeSyncAdapter(NativeSyncDriver(CFG, _hd(native_root)))
    adapter._syncer.s3 = RecordingS3Client(native_root / "S3_SIM")
    try:
        await adapter.finish_pending()
        await drain(adapter._syncer, timeout=180.0)
    finally:
        await teardown_driver(adapter._syncer)
    leftovers = globmod.glob(
        str(native_root / RunDir.FINISHED.value / "**" / "*.yml"), recursive=True
    )
    assert leftovers == [], f"adapter-routed: unsynced ymls remain: {leftovers}"

    _assert_zero_diffs(legacy_set, native_root, "adapter-routed")
