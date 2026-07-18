"""Shared fixtures for the P2c native-sync tests.

assert_source_parity here supersedes native_fixtures.assert_source_parity for
the sync re-body: HelaoYml is property-heavy and AsyncRWLock's lock context
managers are @asynccontextmanager-wrapped, so members are resolved via
inspect.getattr_static + property/staticmethod/wraps unwrapping before
getsource. Tree builders mirror the proven fixture shape of
helao/core/tests/unit_test_sync_process_recovery.py (bare SyncDriver on
tempdir trees; hermetic — no AWS/API).

Tests layer — may import anything (boundary rule)."""

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
REGION_START = 62  # first line of the verbatim legacy region (LOGGER = ...)


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


def assert_verbatim_region(end_line: int) -> None:
    """Legacy lines REGION_START..end_line must appear byte-identical in the
    native module (contiguous-copy capstone; complements per-member pins).
    Reads the LIVE legacy file, so it also pins against legacy drift."""
    legacy = LEGACY_SYNC_PATH.read_text().splitlines(keepends=True)
    region = "".join(legacy[REGION_START - 1 : end_line])
    native = NATIVE_SYNC_PATH.read_text()
    assert region in native, (
        f"legacy lines {REGION_START}..{end_line} are not byte-identical "
        f"inside {NATIVE_SYNC_PATH.name}"
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
