"""P2c D3 gate: direct-drive on-tree parity of the native SyncDriver.

Input: a pre-sync RUNS_FINISHED tree reconstructed from the GM-1 golden via
the native ``reset_sync`` (the goldens are post-sync; reset_sync is the
pipeline's own reversal). Two copies of that tree are driven with a
RecordingS3Client -- one through the raw driver, one through
``NativeSyncAdapter`` -- and outputs are compared with harness.parity.run_parity
-- THE golden gate comparator -- asserting 0 diffs across the run tree,
PROCESSES -prc.yml, S3_SIM payloads, and manifest.jsonl.

Since Task 10 the pipeline neither promotes nor zips (spec D9), so the
post-sync tree compared here is the input tree plus its ``.prg`` receipts,
not a RUNS_SYNCED zip. The GM-1 golden was captured under the old pipeline,
so the golden compare lands in its artifact-bounded branch: the re-driven
tree diverges from the golden, and a second re-drive must diverge by exactly
the same amount.

The core twin this once ran against is deleted; the two sides here are both
native, so the raw-versus-raw comparison is a determinism check, not an
independent baseline. The independent baseline is the committed GOLDEN in the
F1a section.

Needs the GM-1 golden set (``HELAO_GOLDENS``); skipped where it is absent."""

import glob as globmod
import json
import os
import shutil
from pathlib import Path

import pytest

from harness.parity import run_parity
from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir
from helao.deploy.test.servers.action.sim_db_server import RecordingS3Client
from helao.hexagon.adapters.native.sync_adapter import NativeSyncAdapter
from helao.hexagon.adapters.native.sync_driver import SyncDriver as NativeSyncDriver
from helao.helpers.run_state import _prg_is_complete
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
    """Golden post-sync root -> pre-sync RUNS_FINISHED tree (native reset_sync)."""
    stage = tmp_path / "stage"
    shutil.copytree(GOLDEN / "root", stage)
    zips = globmod.glob(
        str(stage / RunDir.SYNCED.value / "**" / "*.zip"), recursive=True
    )
    assert len(zips) == 1, f"expected exactly one synced sequence zip, got {zips}"
    prep = NativeSyncDriver(CFG, _hd(stage))
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


def _unsynced(root: Path) -> list:
    """Records under *root* whose ``.prg`` receipt does not say they shipped.

    "Shipped" used to mean "no longer under RUNS_FINISHED", because the
    syncer promoted the tree. Task 10 deleted the promotion (spec D9): a
    record stays exactly where it was written and the ``.prg`` sidecar beside
    its yml is the receipt, so that is what this reads.
    """
    return [
        p
        for p in globmod.glob(
            str(root / RunDir.FINISHED.value / "**" / "*.yml"), recursive=True
        )
        if Path(p).stem.endswith(("-seq", "-exp", "-act"))
        and not _prg_is_complete(Path(p).with_suffix(".prg"))
    ]


async def _drive(root: Path, driver_cls) -> None:
    drv = driver_cls(CFG, _hd(root))
    drv.s3 = RecordingS3Client(root / "S3_SIM")
    try:
        await drv.finish_pending()
        await drain(drv, timeout=180.0)
    finally:
        await teardown_driver(drv)
    leftovers = _unsynced(root)
    assert (
        leftovers == []
    ), f"{driver_cls.__module__}: unsynced ymls remain: {leftovers}"


def _assert_zero_diffs(raw_set: Path, native_root: Path, tag: str) -> None:
    report = run_parity(raw_set, native_root)
    assert report["status"] == "pass" and report["n_diffs"] == 0, (
        f"[{tag}] raw-vs-second-drive sync parity failed "
        f"(run {report['run_id']}):\n{json.dumps(report, indent=2, default=str)}"
    )


async def _prepare_both_sides(tmp_path: Path):
    stage = await _reconstruct_input(tmp_path)
    raw_set = tmp_path / "raw_set"
    raw_set.mkdir()
    shutil.copytree(stage, raw_set / "root")
    shutil.copy(GOLDEN / "provenance.yml", raw_set / "provenance.yml")
    native_root = tmp_path / "native_root"
    shutil.copytree(stage, native_root)
    await _drive(raw_set / "root", NativeSyncDriver)
    await _drive(native_root, NativeSyncDriver)
    return raw_set, native_root


@pytest.mark.asyncio
async def test_direct_drive_tree_parity(tmp_path):
    raw_set, native_root = await _prepare_both_sides(tmp_path)
    _assert_zero_diffs(raw_set, native_root, "full-sync")

    # --- F1a: non-tautological immutable-golden check --------------------
    # The raw-vs-second-drive compare above is tautological (byte-identical
    # driver bodies trivially match). Additionally compare each re-driven
    # side against the immutable committed GOLDEN itself. reset_sync then
    # re-sync is not guaranteed to be a perfect identity under the
    # comparator, so gate the strong assertion on whether the raw run itself
    # round-trips clean against the golden.
    raw_vs_golden = run_parity(GOLDEN, raw_set / "root")
    native_vs_golden = run_parity(GOLDEN, native_root)
    if raw_vs_golden["n_diffs"] == 0:
        # Reconstruction is a clean round-trip -> native must reproduce the
        # immutable golden bytes exactly. This is the strong, non-tautological
        # gate: native output == the real captured GM-1 run, not just == a
        # freshly-run raw sibling.
        assert native_vs_golden["n_diffs"] == 0, (
            "[golden] native failed to reproduce immutable GM-1 golden bytes "
            f"(run {native_vs_golden['run_id']}):\n"
            f"{json.dumps(native_vs_golden, indent=2, default=str)}"
        )
    else:
        # reset_sync -> finish_pending round-trip is not a perfect identity
        # under the comparator (the raw run itself diverges from the golden), so
        # the golden compare is artifact-bounded and can't cleanly isolate
        # native drift on its own. The primary byte-parity gate is the
        # raw-vs-second-drive 0-diff assertion above; here we additionally
        # require native to diverge from the golden by EXACTLY the same
        # amount as the raw run does (no additional native-introduced drift).
        assert native_vs_golden["n_diffs"] == raw_vs_golden["n_diffs"], (
            "[golden] native introduced additional drift vs golden beyond "
            "the raw run's own reset-round-trip artifacts "
            f"(raw={raw_vs_golden['n_diffs']} diffs, "
            f"native={native_vs_golden['n_diffs']} diffs):\n"
            f"raw_vs_golden={json.dumps(raw_vs_golden, indent=2, default=str)}\n"
            f"native_vs_golden={json.dumps(native_vs_golden, indent=2, default=str)}"
        )


@pytest.mark.asyncio
async def test_a_second_finish_pending_is_a_no_op(tmp_path):
    """What the GM-5 reset/re-sync round trip was really guarding.

    That test reset the synced output from its sequence zip and re-drove it.
    Task 10 removed the promotion and the zip (spec D9), so there is no zip
    to reset and nothing to move back -- but the property underneath it
    survives and is the one that matters now that records stay in place: a
    second sweep over an already-shipped tree must re-upload nothing, on both
    drivers, and leave the tree byte-identical. Without the ``.prg`` filter
    in ``list_pending*`` (plan A1) every record would be re-enqueued here.
    """
    raw_set, native_root = await _prepare_both_sides(tmp_path)
    for root, driver_cls in (
        (raw_set / "root", NativeSyncDriver),
        (native_root, NativeSyncDriver),
    ):
        drv = driver_cls(CFG, _hd(root))
        drv.s3 = RecordingS3Client(root / "S3_SIM")
        try:
            assert drv.list_pending() == [], "a shipped sequence is still pending"
            assert await drv.finish_pending() == []
            await drain(drv, timeout=180.0)
        finally:
            await teardown_driver(drv)
        assert _unsynced(root) == []
    _assert_zero_diffs(raw_set, native_root, "second-pass")


@pytest.mark.asyncio
async def test_native_sync_adapter_drives_parity(tmp_path):
    """F1b: exercise NativeSyncAdapter's delegation surface (not just the raw
    NativeSyncDriver) in the gate. One side is driven through the adapter,
    the other through the raw driver; outputs must still show 0
    diffs under run_parity."""
    stage = await _reconstruct_input(tmp_path)
    raw_set = tmp_path / "raw_set"
    raw_set.mkdir()
    shutil.copytree(stage, raw_set / "root")
    shutil.copy(GOLDEN / "provenance.yml", raw_set / "provenance.yml")
    native_root = tmp_path / "native_root"
    shutil.copytree(stage, native_root)

    await _drive(raw_set / "root", NativeSyncDriver)

    adapter = NativeSyncAdapter(NativeSyncDriver(CFG, _hd(native_root)))
    adapter._syncer.s3 = RecordingS3Client(native_root / "S3_SIM")
    try:
        await adapter.finish_pending()
        await drain(adapter._syncer, timeout=180.0)
    finally:
        await teardown_driver(adapter._syncer)
    leftovers = _unsynced(native_root)
    assert leftovers == [], f"adapter-routed: unsynced ymls remain: {leftovers}"

    _assert_zero_diffs(raw_set, native_root, "adapter-routed")
