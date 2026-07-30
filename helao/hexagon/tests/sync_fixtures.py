"""Shared fixtures for the P2c native-sync tests.

assert_source_parity here supersedes native_fixtures.assert_source_parity for
the sync re-body: HelaoYml is property-heavy and AsyncRWLock's lock context
managers are @asynccontextmanager-wrapped, so members are resolved via
inspect.getattr_static + property/staticmethod/wraps unwrapping before
getsource. Tree builders mirror the proven fixture shape of
helao/core/tests/unit_test_sync_process_recovery.py (bare SyncDriver on
tempdir trees; hermetic — no AWS/API).

Tests layer — may import anything (boundary rule)."""

import ast
import asyncio
import inspect
from datetime import datetime
from pathlib import Path

from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir
from helao.helpers.yml_tools import yml_dumps

LEGACY_SYNC_PATH = (
    Path(__file__).resolve().parents[2] / "core" / "drivers" / "data" / "sync_driver.py"
)
NATIVE_SYNC_PATH = (
    Path(__file__).resolve().parents[1] / "adapters" / "native" / "sync_driver.py"
)
#: The verbatim region is the whole of legacy ``SyncDriver`` and the
#: module-level definitions above it: it starts at the first statement below
#: the import block and stops just before the Base-coupled ``HelaoSyncer``
#: subclass, which the native module deliberately replaces with
#: ``NativeSyncer`` (D2) and therefore does NOT copy.
#:
#: BOTH boundaries are DERIVED from sentinels rather than hardcoded, because a
#: literal line number silently rots.
#:
#: The end drifted twice in two commits (``d88cabe3`` removed ``to_api``,
#: ``dadd5e44`` added ``has_pending_work``) until the literal had slid past
#: ``class HelaoSyncer`` and the pin was asserting byte-identity for a class
#: the native module is supposed to omit.
#:
#: The start was a literal ``62`` until an import-sort sweep exposed the same
#: rot in the other direction: legacy carried ``from glob import glob``
#: orphaned below a blank line, so sorting hoisted it into the main import
#: block and moved ``LOGGER`` from line 63 to 57. Nothing inside the region
#: changed -- the literal was simply measuring from the wrong end of a block
#: that any import-only tool may legally reflow.
HELAO_SYNCER_SENTINEL = "class HelaoSyncer(SyncDriver):"
REGION_START_SENTINEL = "LOGGER = logging.make_logger"


def _source_of(owner, name: str) -> str:
    obj = inspect.getattr_static(owner, name)
    if isinstance(obj, property):
        obj = obj.fget
    elif isinstance(obj, (staticmethod, classmethod)):
        obj = obj.__func__
    return inspect.getsource(inspect.unwrap(obj))  # type: ignore[reportArgumentType]


def assert_source_parity(native_owner, legacy_owner, names) -> None:
    """Byte-parity pin: each member's source must equal its legacy twin."""
    diffs = []
    for name in names:
        if _source_of(native_owner, name) != _source_of(legacy_owner, name):
            diffs.append(name)
    assert not diffs, f"native members drifted from legacy source: {diffs}"


def verbatim_region_start(legacy_lines: list[str]) -> int:
    """1-based legacy line where the verbatim region begins: the ``LOGGER = ...``
    assignment, i.e. the first statement below the import block.

    Fails loud if the sentinel is gone or ambiguous, since a silently-wrong
    start would slide the region into the import block -- where an import-only
    tool may legally reorder lines -- and make the pin fail for a reason that
    has nothing to do with the copied code.
    """
    hits = [
        i
        for i, line in enumerate(legacy_lines)
        if line.startswith(REGION_START_SENTINEL)
    ]
    assert len(hits) == 1, (
        f"expected exactly one {REGION_START_SENTINEL!r} in "
        f"{LEGACY_SYNC_PATH.name}, found {len(hits)}"
    )
    return hits[0] + 1  # 0-based index -> 1-based line


def verbatim_region_end(legacy_lines: list[str]) -> int:
    """1-based legacy line where the verbatim region ends: the last line of
    ``SyncDriver``, i.e. the final non-blank line before ``HelaoSyncer``.

    Fails loud if the sentinel is gone, since a silently-missing sentinel would
    make the pin vacuous.
    """
    sentinel = [
        i
        for i, line in enumerate(legacy_lines)
        if line.startswith(HELAO_SYNCER_SENTINEL)
    ]
    assert len(sentinel) == 1, (
        f"expected exactly one {HELAO_SYNCER_SENTINEL!r} in "
        f"{LEGACY_SYNC_PATH.name}, found {len(sentinel)}"
    )
    end = sentinel[0]  # 0-based index of the sentinel == 1-based line above it
    start = verbatim_region_start(legacy_lines)
    while end > start and not legacy_lines[end - 1].strip():
        end -= 1  # back over the blank run between the two classes
    return end


def assert_verbatim_region(end_line: int | None = None) -> None:
    """The legacy verbatim region must appear byte-identical in the native
    module (contiguous-copy capstone; complements per-member pins). Reads the
    LIVE legacy file, so it also pins against legacy drift.

    Both bounds are sentinel-derived; ``end_line`` defaults to the derived end
    of ``SyncDriver``, and is passed explicitly only to pin a narrower prefix.
    """
    legacy = LEGACY_SYNC_PATH.read_text().splitlines(keepends=True)
    start_line = verbatim_region_start(legacy)
    if end_line is None:
        end_line = verbatim_region_end(legacy)
    region = "".join(legacy[start_line - 1 : end_line])
    assert HELAO_SYNCER_SENTINEL not in region, (
        f"the verbatim region reaches into {HELAO_SYNCER_SENTINEL!r}, which the "
        "native module replaces with NativeSyncer and does not copy"
    )
    native = NATIVE_SYNC_PATH.read_text()
    assert region in native, (
        f"legacy lines {start_line}..{end_line} are not byte-identical "
        f"inside {NATIVE_SYNC_PATH.name}"
    )


def assert_region_holds_no_imports() -> None:
    """The verbatim region must contain no import statement.

    This is what makes the pin robust against import-only tooling (isort /
    ``ruff --select I``): such a tool may reorder, merge, or hoist imports and
    thereby shift every line number in the file, but it cannot touch a region
    that holds no imports. Sorting all ten pin files was measured to leave
    every member body byte-identical for exactly this reason -- the only
    movement was the import block above the region.

    Fails loud if a future edit drops an import below the region start (the
    orphaned ``from glob import glob`` that used to sit just above it is the
    live example of how easily that happens), because at that point an import
    sweep CAN rewrite pinned bytes and the sweep must exclude these files
    instead -- the way black's ``force-exclude`` in pyproject.toml already
    does, since reformatting is not body-preserving the way sorting is.
    """
    source = LEGACY_SYNC_PATH.read_text()
    lines = source.splitlines(keepends=True)
    start, end = verbatim_region_start(lines), verbatim_region_end(lines)
    offenders = [
        (node.lineno, ast.get_source_segment(source, node))
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and start <= node.lineno <= end
    ]
    assert not offenders, (
        f"import statements inside the verbatim region "
        f"(lines {start}..{end}) of {LEGACY_SYNC_PATH.name}: {offenders}. "
        "An import-sort sweep could rewrite pinned bytes; either move them "
        "above the region or exclude the pin files from the sweep."
    )


def make_sync_driver(tmp_root, cls):
    """Bare sync driver on a tempdir tree; hermetic (s3/api unset).

    Must be called with a running event loop (SyncDriver.__init__ spawns the
    syncer worker tasks). Callers are responsible for teardown_driver()."""
    hd = HelaoDirs(
        root=Path(tmp_root),
        save_root=Path(tmp_root) / RunDir.ACTIVE.value,
        process_root=Path(tmp_root) / "PROCESSES",
    )
    cfg = {"aws_bucket": "test-bucket", "max_tasks": 1}
    return cls(cfg, hd)


async def teardown_driver(drv) -> None:
    for task in drv.syncer_loops.values():
        task.cancel()
    await asyncio.gather(*drv.syncer_loops.values(), return_exceptions=True)


async def drain(drv, timeout: float = 120.0) -> None:
    """Wait until the queue, running set, and dedup set are stably empty."""
    deadline = asyncio.get_running_loop().time() + timeout
    stable = 0
    while stable < 3:
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError(
                f"sync drain timed out: qsize={drv.task_queue.qsize()} "
                f"running={list(drv.running_tasks)} task_set={drv.task_set}"
            )
        idle = (
            drv.task_queue.qsize() == 0 and not drv.running_tasks and not drv.task_set
        )
        stable = stable + 1 if idle else 0
        await asyncio.sleep(0.1)


# --- tree builders (mirror unit_test_sync_process_recovery.py:39-117) ------


def write_yml(path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dumped = yml_dumps(meta)
    if isinstance(dumped, bytes):
        dumped = dumped.decode("utf-8")
    path.write_text(dumped, encoding="utf-8")


def ts(second: int) -> str:
    """Filename timestamp stem that HelaoYml can parse (%y%m%d.%H%M%S%f)."""
    return datetime(2026, 6, 10, 12, 0, second, 100).strftime("%y%m%d.%H%M%S%f")


def mk_uuid(tag: int) -> str:
    return f"00000000-0000-0000-0000-{tag:012d}"


def exp_meta(uuid: str, process_order_groups=None) -> dict:
    meta = {
        "experiment_uuid": uuid,
        "experiment_name": "test_exp",
        "sequence_uuid": mk_uuid(999),
        "technique_name": "test_tech",
        "run_type": "test",
        "experiment_params": {"foo": "bar"},
    }
    if process_order_groups is not None:
        meta["process_order_groups"] = process_order_groups
    return meta


def act_meta(order: int, process_finish: bool = False) -> dict:
    return {
        "action_uuid": mk_uuid(order),
        "action_name": "test_action",
        "action_order": order,
        "action_actual_order": order,
        "orch_submit_order": order,
        "action_split": 0,
        "action_timestamp": ts(order + 1),
        "process_finish": process_finish,
        "process_contrib": ["action_params"],
        "action_params": {f"p{order}": order},
        "technique_name": "test_tech",
    }


def make_exp_tree(root: Path, runs: str, exp_uuid: str, process_order_groups=None):
    """Create <root>/<runs>/26.23/0610/<seq>/<exp>/ and return the exp yml path."""
    exp_dir = (
        root / runs / "26.23" / "0610" / f"{ts(0)}__test__seq" / f"{ts(0)}__test_exp"
    )
    exp_yml = exp_dir / f"{ts(0)}-exp.yml"
    write_yml(exp_yml, exp_meta(exp_uuid, process_order_groups))
    return exp_yml


def make_action(exp_yml: Path, order: int, process_finish: bool = False) -> Path:
    """Create a child action dir + yml under the experiment dir; return act yml."""
    act_dir = exp_yml.parent / f"{order}__0__srv__test_action"
    act_yml = act_dir / f"{ts(order + 1)}-act.yml"
    write_yml(act_yml, act_meta(order, process_finish))
    return act_yml
