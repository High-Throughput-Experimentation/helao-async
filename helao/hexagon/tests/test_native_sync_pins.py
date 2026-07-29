"""Source-parity pins for the P2c native sync re-body (D1).

Every pinned member's source must be byte-identical to the LIVE legacy
module (helao/core/drivers/data/sync_driver.py) — proves the copy is exact
AND pins against future legacy drift. The verbatim-region test is the
capstone: the whole contiguous legacy region must appear unmodified inside
the native module. The region grew per task during P2c (T2: 528 ... T7: the
full region); since T7 it spans everything up to the end of legacy
``SyncDriver``, derived from the ``HelaoSyncer`` sentinel rather than pinned
to a line number that shifts on every legacy edit."""

import helao.core.drivers.data.sync_driver as legacy_mod
import helao.hexagon.adapters.native.sync_driver as native_mod
from helao.hexagon.tests.sync_fixtures import (
    assert_source_parity,
    assert_verbatim_region,
)

MODULE_FUNCS = ["dict2json", "move_to_synced", "revert_to_finished"]

ASYNC_RW_LOCK = ["__init__", "read_locked", "write_locked"]

HELAO_YML = [
    "__init__",
    "parts",
    "check_paths",
    "exists",
    "__repr__",
    "type",
    "timestamp",
    "status",
    "meta_status",
    "is_estopped",
    "rename",
    "status_idx",
    "relative_path",
    "active_path",
    "finished_path",
    "synced_path",
    "cleanup",
    "list_children",
    "active_children",
    "finished_children",
    "synced_children",
    "children",
    "misc_files",
    "lock_files",
    "hlo_files",
    "parent_path",
    "write_meta",
]


PROGRESS = [
    "__init__",
    "yml",
    "list_unfinished_procs",
    "read_dict",
    "write_dict",
    "s3_done",
    "api_done",
    "remove_prg",
]


def test_verbatim_region():
    assert_verbatim_region()


def test_module_functions_parity():
    assert_source_parity(native_mod, legacy_mod, MODULE_FUNCS)


def test_async_rw_lock_parity():
    assert_source_parity(native_mod.AsyncRWLock, legacy_mod.AsyncRWLock, ASYNC_RW_LOCK)


def test_helao_yml_parity():
    assert_source_parity(native_mod.HelaoYml, legacy_mod.HelaoYml, HELAO_YML)


def test_progress_parity():
    assert_source_parity(native_mod.Progress, legacy_mod.Progress, PROGRESS)


SYNC_DRIVER_CORE = [
    "__init__",
    "try_remove_empty",
    "cleanup_root",
    "sync_exit_callback",
    "_rel_under_runs",
    "_node_keys",
    "_get_seq_lock",
    "_get_exp_lock",
    "_acquire_hierarchy_locks",
    "syncer",
    "get_progress",
    "enqueue_yml",
]


def test_sync_driver_core_parity():
    assert_source_parity(native_mod.SyncDriver, legacy_mod.SyncDriver, SYNC_DRIVER_CORE)


SYNC_DRIVER_YML = ["sync_yml"]


def test_sync_yml_parity():
    assert_source_parity(native_mod.SyncDriver, legacy_mod.SyncDriver, SYNC_DRIVER_YML)


SYNC_DRIVER_PROCESS = ["update_process", "reconcile_processes", "sync_process"]


def test_process_recovery_surface_parity():
    """The 728a663c fix must be byte-identical (plan MUST-PRESERVE)."""
    assert_source_parity(
        native_mod.SyncDriver, legacy_mod.SyncDriver, SYNC_DRIVER_PROCESS
    )


SYNC_DRIVER_TAIL = [
    "to_s3",
    "list_pending",
    "list_pending_acts",
    "list_pending_exps",
    "finish_pending",
    "reset_sync",
    "shutdown",
    "unsync_dir",
]


def test_sync_driver_tail_parity():
    assert_source_parity(native_mod.SyncDriver, legacy_mod.SyncDriver, SYNC_DRIVER_TAIL)
