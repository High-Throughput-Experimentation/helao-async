"""Unit tests for the ``ActionFinalizer`` collaborator extracted from ``Active``
(CARDS P6, Stage S8 -- the LAST and highest-risk ``Active`` extraction): the
finish / split / substitute close-out cluster (``split_and_keep_active`` /
``split_and_finish_prev_uuids`` / ``finish_all`` / ``split`` / ``substitute`` /
``finish`` / ``_finish`` / ``finish_manual_action``).

``test_active_golden_master.py --check`` is the whole-record byte gate for the
finish-produced ``.hlo`` output across the full ``Active`` lifecycle (including
the S8 finish-drain scenario that reaches ``finish`` with data still in flight);
this module is the S8-specific behavior-preservation gate that drives the close-
out directly and asserts the pieces in isolation:

* ``finish`` DRAINS a still-in-flight packet to the ``.hlo`` before closing the
  file (the data-loss-on-finish class this stage risks) -- the late row is read
  back off disk.
* ``split`` / ``split_and_keep_active`` fork a child action with fresh file
  connections, mark the parent split, and (via ``finish_all``) finish the whole
  chain -- the orphaned-split-child class.
* ``substitute`` closes every open file connection.
* every ``Active`` delegator forwards to ``active.action_finalizer`` and the
  finish state (``action`` / ``action_list`` / ``num_data_queued`` /
  ``num_data_written`` / ``file_conn_dict``) stays on ``Active``, never cached
  on the collaborator.

Mirrors the ``Base.__new__`` bypass fixture used by
``unit_test_active_executor.py`` / ``test_active_golden_master.py``'s
``_make_base`` + ``_mk_action``, and patches the disk/network module-globals the
close-out reaches -- on BOTH ``base`` and ``active_finalizer`` (the moved
``_finish`` resolves ``move_dir`` / ``async_private_dispatcher`` / ``set_time``
from the finalizer module) -- so no real relocation/RPC runs.

Hermetic: no network; real (temp-dir) disk I/O so the drained rows are checked
against genuine filesystem behavior.
"""

__all__ = ["active_finalizer_unit_test"]

import asyncio
import os
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from helao.core.tests._test_utils import TestReporter
import helao.core.servers.base as base_module
import helao.core.servers.active_finalizer as finalizer_module
from helao.core.servers.base import Base, Active
from helao.core.servers.active_finalizer import ActionFinalizer
from helao.core.error import ErrorCodes
from helao.core.models.data import DataModel
from helao.core.models.file import FileConnParams, HloFileGroup
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.helpers.active_params import ActiveParams
from helao.helpers.dequedict import DequeDict
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.premodels import Action


_FIXED_DT = datetime(2026, 1, 2, 3, 4, 5, 678901)
_SEED = {"n": 0}


def _make_base(save_root: str) -> Base:
    """Build a bare ``Base`` with every attribute the finish/split path touches."""
    base = Base.__new__(Base)
    base.app = SimpleNamespace(driver=None)
    base.server = MachineModel(
        server_name="ACTSRV", machine_name="test-machine", hostname="127.0.0.1", port=8000
    )
    base.world_cfg = {
        "dummy": False,
        "simulation": False,
        "root": str(Path(save_root).parent),
    }
    base.ntp_offset = 0.0
    base.helaodirs = SimpleNamespace(save_root=save_root)
    base.aloop = asyncio.get_running_loop()
    base.status_q = MultisubscriberQueue()
    base.data_q = MultisubscriberQueue()
    base.status_clients = set()
    base.actives = {}
    base.history = DequeDict(maxlen=200)
    base.executors = {}
    base.local_action_task_queue = []
    base.hlo_postprocessors = []
    base.hlo_postprocess_libs = []
    base.live_q = MultisubscriberQueue()
    base.live_buffer = {}
    base._init_collaborators()
    return base


def _mk_action() -> Action:
    """Non-manual ``Action`` (parent seq/exp set) with data saving enabled and a unique uuid."""
    _SEED["n"] += 1
    n = _SEED["n"]
    return Action(
        action_name="fintest",
        action_abbr="fin",
        orch_key="ACTSRV",
        orch_host="127.0.0.1",
        orch_port=8000,
        action_uuid=UUID(int=0xA0000000000000000000000000000000 + n),
        action_timestamp=_FIXED_DT,
        sequence_uuid=UUID(int=0xB0000000000000000000000000000000 + n),
        sequence_name="seq_fin",
        sequence_label="ut",
        sequence_timestamp=_FIXED_DT,
        experiment_uuid=UUID(int=0xC0000000000000000000000000000000 + n),
        experiment_name="exp_fin",
        experiment_timestamp=_FIXED_DT,
        save_data=True,
    )


def _mk_active(base: Base) -> Active:
    action = _mk_action()
    dflt = base.dflt_file_conn_key()
    ap = ActiveParams(
        action=action,
        file_conn_params_dict={
            dflt: FileConnParams(
                file_conn_key=dflt,
                json_data_keys=["t", "v"],
                file_type="fin__test_file",
                file_group=HloFileGroup.helao_files,
            )
        },
        aux_listen_uuids=[],
    )
    return Active(base, ap)


async def _drain(active: Active, timeout_s: float = 5.0):
    """Block until the data logger has consumed every enqueued packet."""
    waited = 0.0
    while active.num_data_queued > active.num_data_written and waited < timeout_s:
        await asyncio.sleep(0.01)
        waited += 0.01
    await asyncio.sleep(0.02)


def _read_hlo_rows(save_root: str) -> list:
    """Return the '%%'-separated data lines of every .hlo file under save_root."""
    rows = []
    for dirpath, _dirnames, filenames in os.walk(save_root):
        for fn in filenames:
            if not fn.endswith(".hlo"):
                continue
            with open(os.path.join(dirpath, fn), "r", encoding="utf-8") as f:
                body = f.read()
            if "%%" in body:
                after = body.split("%%", 1)[1]
                rows.extend(ln for ln in after.splitlines() if ln.strip())
    return rows


class _PatchGlobals:
    """Patch the disk/network module-globals ``finish`` reaches so no real IO/RPC runs.

    Patches BOTH ``base`` and ``active_finalizer`` (the moved ``_finish`` resolves
    ``move_dir`` / ``async_private_dispatcher`` / ``set_time`` from the finalizer
    module's own namespace)."""

    def __enter__(self):
        async def _noop_move_dir(hobj, base=None, retry_delay=5):
            return None

        async def _noop_dispatch(*args, **kwargs):
            return {}, ErrorCodes.none

        async def _noop_copy(src, dst, **kwargs):
            return None

        def _fixed_set_time(offset: float = 0):
            return _FIXED_DT

        self._orig = {
            (base_module, "move_dir"): base_module.move_dir,
            (base_module, "async_private_dispatcher"): base_module.async_private_dispatcher,
            (base_module, "async_copy"): base_module.async_copy,
            (finalizer_module, "move_dir"): finalizer_module.move_dir,
            (finalizer_module, "async_private_dispatcher"): finalizer_module.async_private_dispatcher,
            (finalizer_module, "set_time"): finalizer_module.set_time,
        }
        base_module.move_dir = _noop_move_dir
        base_module.async_private_dispatcher = _noop_dispatch
        base_module.async_copy = _noop_copy
        finalizer_module.move_dir = _noop_move_dir
        finalizer_module.async_private_dispatcher = _noop_dispatch
        finalizer_module.set_time = _fixed_set_time
        return self

    def __exit__(self, *exc):
        for (mod, name), val in self._orig.items():
            setattr(mod, name, val)
        return False


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------


async def _check_collaborator_wired() -> bool:
    base = _make_base(tempfile.mkdtemp())
    active = _mk_active(base)
    return (
        isinstance(active.action_finalizer, ActionFinalizer)
        and active.action_finalizer.active is active
        # finish state stays on Active, not cached on the collaborator
        and hasattr(active, "action_list")
        and hasattr(active, "num_data_queued")
        and hasattr(active, "num_data_written")
        and hasattr(active, "file_conn_dict")
        and hasattr(active, "finish_lock")
        and not hasattr(active.action_finalizer, "action_list")
        and not hasattr(active.action_finalizer, "num_data_queued")
    )


async def _check_finish_drains_late_data() -> bool:
    """finish flushes a still-in-flight packet to the .hlo before closing.

    A drained packet opens the file; a second packet is enqueued synchronously
    (nowait) and finish() is called immediately, so it is undrained at finish
    entry. The late row must be present on disk after finish."""
    save_root = tempfile.mkdtemp()
    base = _make_base(save_root)
    with _PatchGlobals():
        active = _mk_active(base)
        await active.myinit()
        await asyncio.sleep(0.02)
        dflt = base.dflt_file_conn_key()

        await active.enqueue_data_dflt({"t": 0, "v": 0})
        await _drain(active)

        active.enqueue_data_nowait(
            DataModel(data={dflt: {"t": 1, "v": 111}}, errors=[], status=HloStatus.active)
        )
        undrained_at_entry = active.num_data_queued > active.num_data_written

        result = await active.finish()
        await asyncio.sleep(0.02)

        rows = _read_hlo_rows(save_root)
        return (
            undrained_at_entry is True
            and result is active.action
            and HloStatus.finished in active.action.action_status
            and any('"v": 0' in r for r in rows)
            # the late, undrained row survived the finish drain
            and any('"v": 111' in r for r in rows)
            and active.file_conn_dict == {}
            # everything queued was written before close (no lost data)
            and active.num_data_written >= active.num_data_queued
        )


async def _check_split_keep_active_then_finish_all() -> bool:
    """split forks a child with fresh file conns + marks the parent split;
    finish_all then finishes the whole chain."""
    save_root = tempfile.mkdtemp()
    base = _make_base(save_root)
    with _PatchGlobals():
        active = _mk_active(base)
        await active.myinit()
        await asyncio.sleep(0.02)

        parent_uuid = active.action.action_uuid
        await active.enqueue_data_dflt({"t": 0, "v": 0})
        await _drain(active)

        new_keys = await active.split(uuid_list=[])
        await asyncio.sleep(0.02)

        # after split: a fresh child action is current, the parent is retained
        child_forked = active.action.action_uuid != parent_uuid
        list_grew = len(active.action_list) == 2
        parent_action = active.action_list[1]
        parent_split = HloStatus.split in parent_action.action_status
        # uuid_list=[] keeps every prior action open (nothing finished yet)
        parent_open_after_split = HloStatus.finished not in parent_action.action_status
        child_has_new_conns = (
            len(new_keys) >= 1
            and all(k in active.file_conn_dict for k in new_keys)
        )

        # stream to the child's new file connection, then finish everything
        await active.enqueue_data(
            DataModel(data={new_keys[0]: {"t": 9, "v": 999}}, errors=[], status=HloStatus.active)
        )
        await _drain(active)
        await active.finish_all()
        await asyncio.sleep(0.02)

        both_finished = all(
            HloStatus.finished in a.action_status for a in active.action_list
        )
        rows = _read_hlo_rows(save_root)
        child_row_written = any('"v": 999' in r for r in rows)

        return (
            child_forked
            and list_grew
            and parent_split
            and parent_open_after_split
            and child_has_new_conns
            and both_finished
            and child_row_written
        )


async def _check_substitute_closes_open_files() -> bool:
    """substitute closes every open file connection for the active."""
    save_root = tempfile.mkdtemp()
    base = _make_base(save_root)
    with _PatchGlobals():
        active = _mk_active(base)
        await active.myinit()
        await asyncio.sleep(0.02)

        await active.enqueue_data_dflt({"t": 0, "v": 0})
        await _drain(active)

        open_before = sum(
            1 for fc in active.file_conn_dict.values() if fc.file is not None
        )
        await active.substitute()
        # file objects remain referenced but are now closed
        all_closed = all(
            fc.file is None or fc.file.closed
            for fc in active.file_conn_dict.values()
        )
        # tidy up the still-running data logger so the loop has no dangling task
        active.data_logger.cancel()
        return open_before >= 1 and all_closed is True


async def _check_delegators_forward() -> bool:
    """Every Active finalizer delegator resolves onto action_finalizer (spy each)."""
    base = _make_base(tempfile.mkdtemp())
    active = _mk_active(base)
    calls = []

    async def _spy(name, *a, **k):
        calls.append(name)
        return None

    active.action_finalizer.split_and_keep_active = lambda: _spy("skeep")
    active.action_finalizer.split_and_finish_prev_uuids = lambda: _spy("sprev")
    active.action_finalizer.finish_all = lambda: _spy("fall")
    active.action_finalizer.split = lambda uuid_list=None, new_fileconnparams=None: _spy("split")
    active.action_finalizer.substitute = lambda: _spy("subst")
    active.action_finalizer.finish = lambda finish_uuid_list=None: _spy("finish")
    active.action_finalizer._finish = lambda finish_uuid_list=None: _spy("_finish")
    active.action_finalizer.finish_manual_action = lambda: _spy("manual")

    await active.split_and_keep_active()
    await active.split_and_finish_prev_uuids()
    await active.finish_all()
    await active.split()
    await active.substitute()
    await active.finish()
    await active._finish()
    await active.finish_manual_action()

    return calls == [
        "skeep",
        "sprev",
        "fall",
        "split",
        "subst",
        "finish",
        "_finish",
        "manual",
    ]


async def _run_checks() -> dict:
    return {
        "collaborator_wired": await _check_collaborator_wired(),
        "finish_drains_late_data": await _check_finish_drains_late_data(),
        "split_keep_active_then_finish_all": await _check_split_keep_active_then_finish_all(),
        "substitute_closes_open_files": await _check_substitute_closes_open_files(),
        "delegators_forward": await _check_delegators_forward(),
    }


def active_finalizer_unit_test() -> bool:
    reporter = TestReporter("active_finalizer")
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False

    reporter.section("collaborator construction")
    reporter.check(
        "Active.__init__ builds an ActionFinalizer back-referencing the Active; "
        "action_list/num_data_*/file_conn_dict/finish_lock stay on Active",
        lambda: res["collaborator_wired"],
    )

    reporter.section("finish -> late-data drain (no lost data)")
    reporter.check(
        "finish flushes a still-in-flight packet to the .hlo before closing the "
        "file connections (undrained at entry, present on disk after)",
        lambda: res["finish_drains_late_data"],
    )

    reporter.section("split -> child fork + finish_all")
    reporter.check(
        "split forks a child with fresh file connections and marks the parent "
        "split; finish_all then finishes the whole chain with the child data written",
        lambda: res["split_keep_active_then_finish_all"],
    )

    reporter.section("substitute")
    reporter.check(
        "substitute closes every open file connection for the active",
        lambda: res["substitute_closes_open_files"],
    )

    reporter.section("delegator forwarding")
    reporter.check(
        "Active finalizer delegators forward to active.action_finalizer",
        lambda: res["delegators_forward"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if active_finalizer_unit_test() else 1)
