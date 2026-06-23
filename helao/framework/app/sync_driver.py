"""The async data-sync orchestration driver: drives the pure deciders via ports.

This is the SP6 ``app/`` wiring for the data syncer, the strangler-fig
replacement for the legacy ``helao.core.drivers.data.sync_driver.SyncDriver``.
It is the exact analogue of :class:`helao.framework.app.orch_api.OrchDriver`:
all *decisions* live in the pure :mod:`helao.framework.domain.sync` package
(``decide_sync``, ``Progress``, ``process_fold``, ``should_push_process``,
path math), while THIS module owns the asyncio machinery -- the priority queue,
the worker coroutines, the hierarchical reader/writer locks, the awaits, and the
realisation of every decision through the injected
:class:`~helao.framework.ports.sync_storage.SyncStorage` (synchronous local fs)
and :class:`~helao.framework.ports.cloud_sink.CloudSink` (async egress) ports.

The single ``app/`` exception boundary lives in :meth:`SyncDriver.syncer`: an
unexpected exception in one yml's pipeline is logged and swallowed so the worker
keeps draining the queue (parent spec §6), exactly as legacy lines 928-933.

Ports are INJECTED via the constructor (parent spec D-ports). In particular the
caller owns AWS bootstrapping: if a real ``S3CloudSink`` is the injected
``cloud_sink`` the factory/caller must have called ``load_aws_config`` first --
this class never constructs an ``S3CloudSink`` itself (WIRING OBLIGATION 2).

FastAPI is *not* needed here (this wave exposes no endpoints), so it is not
imported -- mirroring how ``orch_api`` keeps the driver dependency-light.
"""
from __future__ import annotations

import asyncio
import uuid as _uuid
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Callable, Optional, Union

from helao.framework.adapters.loaders import hlo_loader
from helao.framework.domain.sync import paths as syncpaths
from helao.framework.domain.sync.decide import (
    SyncAction,
    build_upload_file_list,
    decide_sync,
    hlo_upload_plan,
    patch_metadata,
)
from helao.framework.domain.sync.process_fold import fold_action_into_process
from helao.framework.domain.sync.progress import Progress, should_push_process
from helao.framework.ports.cloud_sink import CloudSink
from helao.framework.ports.sync_storage import SyncStorage
from helao.framework.support import helao_logging as logging
from helao.framework.support.async_utils import AsyncRWLock

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["SyncDriver"]

# Legacy 1GiB threshold above which an hlo file is converted to parquet rather
# than uploaded as json (sync_driver.py line 1124: ``fp.stat().st_size < 1024**3``).
_HLO_PARQUET_THRESHOLD = 1024**3

# Bound on the move_to_synced "file in use" retry loop (WIRING OBLIGATION 1).
# Legacy looped unbounded with a 1s sleep (sync_driver.py 1271-1274); we bound
# it so a permanently-locked file eventually surfaces rather than hanging the
# worker forever.
_MOVE_RETRY_LIMIT = 60
_MOVE_RETRY_SLEEP = 1.0


def _default_gen_uuid(name: str):
    """Default deterministic UUID5 derivation (legacy used uuid5 over a name)."""
    return _uuid.uuid5(_uuid.NAMESPACE_URL, name)


class SyncDriver:
    """Async data-sync engine: holds the queue + locks, drives the pure deciders.

    Construction injects the two ports plus config; nothing is auto-spawned (the
    worker coroutines start only on :meth:`start`, mirroring ``orch_api``'s
    explicit-start pattern so tests can drive :meth:`sync_yml` directly without a
    running loop).

    Attributes:
        sync_storage: Synchronous local-filesystem tree port.
        cloud_sink: Async object-store + API egress port.
        config: Driver/server config dict (``aws_bucket`` etc.).
        helaodirs: Resolved HELAO directory paths (may be ``None`` in tests).
        max_tasks: Number of concurrent ``syncer`` worker coroutines.
        gen_uuid: Injected ``str -> uuid`` derivation for process folding.
        task_queue: The shared :class:`asyncio.PriorityQueue` of ``(rank, path)``.
        task_set: Names currently queued (enqueue dedup).
        running_tasks: Names currently being synced (in-flight dedup).
    """

    def __init__(
        self,
        sync_storage: SyncStorage,
        cloud_sink: CloudSink,
        config: dict,
        helaodirs=None,
        *,
        max_tasks: int = 4,
        gen_uuid: Callable = _default_gen_uuid,
    ) -> None:
        self.sync_storage = sync_storage
        self.cloud_sink = cloud_sink
        self.config = dict(config or {})
        self.helaodirs = helaodirs
        self.max_tasks = int(self.config.get("max_tasks", max_tasks))
        self.gen_uuid = gen_uuid

        self.bucket = self.config.get("aws_bucket")
        self.auto_analyses = self.config.get("auto_analyze_sequences", {})

        self.task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.task_set: set[str] = set()
        self.running_tasks: dict[str, "asyncio.Task | None"] = {}

        # Hierarchical sync locks keyed by each yml's path relative to RUNS_*
        # (stable as the yml moves between RUNS_FINISHED/SYNCED). seq_locks are
        # reader/writer (descendants read, the sequence sync writes); exp_locks
        # are an exclusive mutex shared by an experiment sync and its actions.
        self.seq_locks: dict[str, AsyncRWLock] = {}
        self.exp_locks: dict[str, asyncio.Lock] = {}

        self.syncer_loops: dict[int, asyncio.Task] = {}

    # --- worker lifecycle ---------------------------------------------------

    def start(self) -> None:
        """Spawn ``max_tasks`` :meth:`syncer` worker coroutines (idempotent).

        Mirrors ``orch_api``'s explicit start: nothing runs until called, so
        unit tests can exercise :meth:`sync_yml` / :meth:`get_progress` directly.
        Legacy spawned these eagerly in ``__init__`` (sync_driver.py 734-738).
        """
        if self.syncer_loops:
            return
        self.syncer_loops = {
            i: asyncio.create_task(self.syncer(), name=f"syncer_loop__{i}")
            for i in range(self.max_tasks)
        }

    async def shutdown(self) -> None:
        """Cancel the worker coroutines and await their teardown."""
        loops = list(self.syncer_loops.values())
        self.syncer_loops = {}
        for task in loops:
            task.cancel()
        for task in loops:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    def sync_exit_callback(self, task: asyncio.Task) -> None:
        """Drop a finished task from ``running_tasks``/``task_set`` (legacy 810-824)."""
        task_name = task.get_name()
        self.running_tasks.pop(task_name, None)
        self.task_set.discard(task_name)

    # --- hierarchical locks -------------------------------------------------

    def _get_seq_lock(self, seq_key: str) -> AsyncRWLock:
        """Get-or-create the per-sequence reader/writer lock (legacy 865-871)."""
        lock = self.seq_locks.get(seq_key)
        if lock is None:
            lock = AsyncRWLock()
            self.seq_locks[seq_key] = lock
        return lock

    def _get_exp_lock(self, exp_key: str) -> asyncio.Lock:
        """Get-or-create the exclusive per-experiment mutex (legacy 873-879)."""
        lock = self.exp_locks.get(exp_key)
        if lock is None:
            lock = asyncio.Lock()
            self.exp_locks[exp_key] = lock
        return lock

    async def _acquire_hierarchy_locks(
        self, stack: AsyncExitStack, yml_path: Path
    ) -> None:
        """Enter the hierarchical sync locks for ``yml_path`` (legacy 881-906).

        Outermost-first acquisition (sequence before experiment) gives one
        global order ruling out deadlock: a sequence writes its sequence lock; an
        experiment/action reads it (siblings parallel) and additionally holds its
        own/parent experiment mutex.
        """
        seq_key, exp_key = syncpaths.node_keys(yml_path)
        if seq_key is None:
            return
        seq_lock = self._get_seq_lock(seq_key)
        if exp_key is None:  # sequence yml -> writer
            await stack.enter_async_context(seq_lock.write_locked())
            return
        await stack.enter_async_context(seq_lock.read_locked())  # exp/act -> reader
        await stack.enter_async_context(self._get_exp_lock(exp_key))

    # --- queue --------------------------------------------------------------

    async def syncer(self) -> None:
        """Worker coroutine: pop one yml, take its locks, run :meth:`sync_yml`.

        ``self.max_tasks`` copies run concurrently. The single ``app/`` exception
        boundary wraps the pipeline body so a crash in one yml is logged and
        swallowed and the worker keeps draining (legacy 908-933).
        """
        while True:
            rank, yml_path = await self.task_queue.get()
            yml_path = Path(yml_path)
            self.task_set.discard(yml_path.name)
            if yml_path.name in self.running_tasks:
                continue
            self.running_tasks[yml_path.name] = asyncio.current_task()
            try:
                async with AsyncExitStack() as locks:
                    await self._acquire_hierarchy_locks(locks, yml_path)
                    await self.sync_yml(yml_path=yml_path, rank=rank)
            except Exception:  # the single app/ exception boundary
                LOGGER.error(f"Error in syncer worker for {yml_path}", exc_info=True)
            finally:
                self.running_tasks.pop(yml_path.name, None)

    async def enqueue_yml(
        self, upath: Union[Path, str], rank: int = 0, rank_limit: int = -5
    ) -> None:
        """Enqueue ``upath`` if not already queued/running (legacy 969-995).

        Args:
            upath: yml path to enqueue.
            rank: Priority (lower runs sooner).
            rank_limit: Floor below which the request is dropped, bounding the
                re-queue recursion.
        """
        yml_path = Path(upath)
        if rank < rank_limit:
            LOGGER.debug(
                f"{yml_path} re-queue rank under {rank_limit}, skipping enqueue."
            )
        elif yml_path.name in self.task_set:
            LOGGER.debug(f"{yml_path} already queued, skipping enqueue.")
        elif yml_path.name in self.running_tasks:
            LOGGER.debug(f"{yml_path} already running, skipping enqueue.")
        else:
            self.task_set.add(yml_path.name)
            await self.task_queue.put((rank, yml_path))
            LOGGER.debug(f"Added {yml_path} to syncer queue at rank {rank}.")

    # --- progress -----------------------------------------------------------

    def get_progress(self, yml_path: Path) -> Progress:
        """Return the ``Progress`` for ``yml_path``, creating the ``.prg`` if absent.

        Reads the ``.prg`` sidecar via ``sync_storage.read_prg``; when missing,
        builds ``Progress.initial`` for the node type and persists it via
        ``sync_storage.write_prg`` (legacy 935-967). ``paths.node_type`` returns
        the abbreviation (``act``/``exp``/``seq``), so it is mapped to the
        expanded type via ``paths.ABR_MAP`` that ``Progress.initial`` expects.
        """
        yml_path = Path(yml_path)
        prg_path = self._prg_for(yml_path)
        existing = self.sync_storage.read_prg(prg_path)
        if existing:
            return Progress.from_dict(
                syncpaths.relative_under_runs(yml_path) or yml_path.name, existing
            )
        meta = self.sync_storage.read_yml(yml_path)
        abbr = syncpaths.node_type(yml_path)
        expanded = syncpaths.ABR_MAP.get(abbr, abbr)
        relpath = syncpaths.relative_under_runs(yml_path) or yml_path.name
        prog = Progress.initial(relpath, expanded, meta)
        self.sync_storage.write_prg(prg_path, prog.to_dict())
        return prog

    @staticmethod
    def _prg_for(yml_path: Path) -> Path:
        """``.prg`` sidecar path for ``yml_path``, ALWAYS under RUNS_SYNCED.

        Legacy keeps the prg at ``self.yml.synced_path.with_suffix(".prg")``
        (sync_driver.py line 557) regardless of where the yml currently lives, so
        the progress doc is stable across the FINISHED->SYNCED move and a resumed
        sync looks in the right tree. ``paths.prg_path`` is a pure same-dir
        helper; we apply ``synced_path`` here at the call site to pin the tree.
        """
        return Path(syncpaths.prg_path(Path(syncpaths.synced_path(yml_path))))

    def _write_progress(self, yml_path: Path, prog: Progress) -> None:
        """Persist ``prog`` to its ``.prg`` sidecar under RUNS_SYNCED."""
        self.sync_storage.write_prg(self._prg_for(yml_path), prog.to_dict())

    # --- the pipeline -------------------------------------------------------

    async def sync_yml(
        self,
        yml_path: Path,
        rank: int = 5,
        retries: int = 3,
        force_s3: bool = False,
        force_api: bool = False,
        compress: bool = False,
    ):
        """Run the full sync pipeline for a single yml (legacy 997-1352).

        Gathers (exists, node status, child statuses) via ``sync_storage`` and
        delegates the head decision to :func:`decide_sync`. On
        ``SKIP``/``SOFT_BLOCK`` returns immediately; on ``REQUEUE_CHILDREN``
        re-enqueues the unsynced children (and self) at the decided ranks; on
        ``PROCEED`` runs the upload/move pipeline.

        Returns:
            The shipped progress dict on a completed PROCEED, ``True`` on SKIP,
            ``False`` on SOFT_BLOCK / REQUEUE_CHILDREN (legacy return contract).
        """
        yml_path = Path(yml_path)
        abbr = syncpaths.node_type(yml_path)  # act/exp/seq
        node_status = syncpaths.status_of(yml_path)

        exists = self.sync_storage.exists(yml_path)
        if not exists:
            # legacy 1027-1031: missing yml -> assume already moved to synced (SKIP).
            return True

        prog = self.get_progress(yml_path)
        already_synced = bool(prog.s3_done and prog.api_done)

        # children one level down (non-actions only). Legacy gathers children
        # across the three SIBLING status trees (sync_driver.py 408-421): a
        # child's status is determined by WHICH tree it lives in, not by parsing
        # the child's own path. Listing only ``yml_path.parent`` (the FINISHED
        # tree) would make every child look "finished" and the active-child
        # SOFT_BLOCK gate unreachable. Each entry is
        # (relpath_under_runs, tree status). Actions have no children.
        child_statuses: list[tuple[str, str]] = []
        rel_to_path: dict[str, Path] = {}
        if abbr != "act":
            tree_dirs = {
                "active": Path(syncpaths.active_path(yml_path)).parent,
                "finished": Path(syncpaths.finished_path(yml_path)).parent,
                "synced": Path(syncpaths.synced_path(yml_path)).parent,
            }
            for tree_status, tree_dir in tree_dirs.items():
                for cp in self.sync_storage.list_children(tree_dir):
                    cp = Path(cp)
                    rel = syncpaths.relative_under_runs(cp) or cp.name
                    child_statuses.append((rel, tree_status))
                    rel_to_path[rel] = cp

        decision = decide_sync(
            exists=exists,
            node_status=node_status,
            child_statuses=child_statuses,
            already_synced=already_synced,
            rank=rank,
        )

        if decision.action == SyncAction.SKIP:
            return True
        if decision.action == SyncAction.SOFT_BLOCK:
            return False
        if decision.action == SyncAction.REQUEUE_CHILDREN:
            # Map RequeueItem relpaths back to real child paths (built from the
            # union of sibling trees above); "" denotes self.
            for item in decision.requeue:
                if item.relpath == "":
                    self.task_set.discard(yml_path.name)
                    await self.enqueue_yml(yml_path, item.rank)
                else:
                    target = rel_to_path.get(item.relpath)
                    if target is not None:
                        await self.enqueue_yml(target, item.rank)
            return False

        # ---- PROCEED (legacy 1108-1352) ------------------------------------
        meta = self.sync_storage.read_yml(yml_path)
        node_dir = yml_path.parent

        # 1. actions: push pending files to S3 (legacy 1108-1206). MUST rebind
        #    prog: the per-file files_s3 map + trimmed files_pending are written
        #    into a NEW Progress; dropping the return would re-persist a stale
        #    prog with an empty files_s3 (legacy accumulates in one dict, 1160-1180).
        if abbr == "act":
            prog = await self._upload_action_files(
                yml_path, prog, meta, compress=compress
            )

        # 2. experiments: finalize processes before pushing the experiment doc
        #    (legacy 1207-1227). MUST rebind prog: the advanced experiment
        #    Progress (process_s3/process_api/process_metas) is otherwise lost
        #    and steps 4-6 would wipe the just-written process bookkeeping.
        if abbr == "exp":
            prog, ok = await self._finalize_processes(yml_path, prog, retries=retries)
            if not ok:
                return False
            metas = prog.to_dict().get("process_metas", {})
            if metas:
                meta["process_list"] = [
                    d["process_uuid"] for _, d in sorted(metas.items())
                ]

        # 3. patch metadata (legacy 1229-1237).
        patched = patch_metadata(meta, syncpaths.ABR_MAP.get(abbr, abbr))
        uuid_key = patched.get(f"{syncpaths.ABR_MAP.get(abbr, abbr)}_uuid")

        # 4. push the yml doc to S3 (legacy 1239-1247).
        if not prog.s3_done or force_s3:
            s3_key = f"{syncpaths.ABR_MAP.get(abbr, abbr)}/{uuid_key}.json"
            s3_ok = await self.cloud_sink.upload_bytes(
                _json_bytes(patched), s3_key, compress=compress
            )
            if s3_ok:
                prog = prog.with_s3_done(True)
                self._write_progress(yml_path, prog)

        # 5. register the yml doc with the API (legacy 1249-1256).
        if not prog.api_done or force_api:
            api_ok = await self.cloud_sink.register_api(
                patched, syncpaths.ABR_MAP.get(abbr, abbr)
            )
            if api_ok:
                prog = prog.with_api_done(True)
                self._write_progress(yml_path, prog)

        # 6. move to synced once both legs are done (legacy 1262-1349).
        if prog.s3_done and prog.api_done:
            for lock_path in self.sync_storage.lock_files(node_dir):
                self.sync_storage.remove(Path(lock_path))
            for fp in list(self.sync_storage.misc_files(node_dir, abbr)) + list(
                self.sync_storage.hlo_files(node_dir)
            ):
                await self._move_to_synced_retry(Path(fp))
            new_yml = await self._move_to_synced_retry(yml_path)

            if abbr == "seq":
                synced_dir = Path(new_yml).parent
                await asyncio.to_thread(self.sync_storage.zip_dir, synced_dir)

            # rewrite the prg's stored yml target then persist next to new path.
            shipped = prog.to_dict()
            shipped["yml"] = str(new_yml)
            prog = Progress.from_dict(prog.yml_relpath, shipped)
            self._write_progress(Path(new_yml), prog)

            # action contributing processes: fold + push (legacy 1346-1349).
            # Legacy resolves the parent against the POST-move (SYNCED) yml
            # (legacy 1285): the action just moved out of RUNS_FINISHED, so its
            # parent must be located in the tree consistent with the moved action.
            if abbr == "act" and meta.get("process_contrib", False):
                await self.update_process(Path(new_yml), meta)

        return {k: v for k, v in prog.to_dict().items() if k != "process_metas"}

    async def _move_to_synced_retry(self, path: Path) -> Path:
        """Move ``path`` FINISHED->SYNCED, retrying past a transient lock.

        WIRING OBLIGATION 1: the ``SyncStorage`` adapter lets ``PermissionError``
        propagate for an in-use file (it dropped legacy's False-on-busy return),
        so replicate legacy's wait-it-out loop (sync_driver.py 1271-1274): retry
        a bounded number of times with a sleep between attempts.
        """
        attempt = 0
        while True:
            try:
                return await asyncio.to_thread(self.sync_storage.move_to_synced, path)
            except PermissionError:
                attempt += 1
                if attempt > _MOVE_RETRY_LIMIT:
                    LOGGER.error(f"{path} still locked after {attempt} tries; giving up.")
                    raise
                LOGGER.debug(f"{path} is in use, retrying ({attempt}).")
                await asyncio.sleep(_MOVE_RETRY_SLEEP)

    async def _upload_action_files(
        self, yml_path: Path, prog: Progress, meta: dict, *, compress: bool
    ) -> Progress:
        """Upload an action's pending HLO/misc files to S3 (legacy 1109-1206).

        Builds the pending list via :func:`build_upload_file_list`, decides
        hlo-vs-parquet per file via :func:`hlo_upload_plan`, uploads through
        ``cloud_sink``, and records each success in the prg ``files_s3`` map.
        Returns the (possibly updated) ``Progress``.
        """
        node_dir = yml_path.parent
        d = prog.to_dict()
        hlo_files = [str(p) for p in self.sync_storage.hlo_files(node_dir)]
        misc_files = [str(p) for p in self.sync_storage.misc_files(node_dir, "act")]
        pending = build_upload_file_list(
            d.get("files_pending", []), d.get("files_s3", {}), hlo_files, misc_files
        )
        files_s3 = dict(d.get("files_s3", {}))
        action_uuid = meta.get("action_uuid")
        remaining = list(pending)
        for sp in pending:
            fp = Path(sp)
            is_hlo = fp.suffix == ".hlo"
            size = self.sync_storage.file_size(fp) if is_hlo else 0
            plan = hlo_upload_plan(size, is_hlo, threshold=_HLO_PARQUET_THRESHOLD)
            ok = False
            if is_hlo and plan == "hlo":
                key = f"raw_data/{action_uuid}/{fp.name}.json"
                if compress:
                    key += ".gz"
                file_meta, file_data = await asyncio.to_thread(hlo_loader.read_hlo, sp)
                ok = await self.cloud_sink.upload_bytes(
                    _json_bytes({"meta": file_meta, "data": file_data}),
                    key,
                    compress=compress,
                )
            elif is_hlo and plan == "parquet":
                key = f"raw_data/{action_uuid}/{fp.stem}.parquet"
                parquet_path = sp.replace(".hlo", ".parquet")
                await asyncio.to_thread(hlo_loader.hlo_to_parquet, fp, parquet_path)
                ok = await self.cloud_sink.upload_file(Path(parquet_path), key)
            else:  # non-hlo: raw file upload (legacy 1160-1165)
                rel = str(fp.name)
                key = f"raw_data/{action_uuid}/{rel}"
                ok = await self.cloud_sink.upload_file(fp, key)
            if ok:
                remaining.remove(sp)
                files_s3[str(fp)] = key
                d = prog.to_dict()
                d["files_pending"] = list(remaining)
                d["files_s3"] = dict(files_s3)
                prog = Progress.from_dict(prog.yml_relpath, d)
                self._write_progress(yml_path, prog)
        return prog

    async def _finalize_processes(
        self, exp_yml: Path, prog: Progress, *, retries: int
    ) -> tuple[Progress, bool]:
        """Drain unfinished process groups for an experiment (legacy 1208-1222).

        Repeatedly forces :meth:`sync_process` until no process group is
        unfinished or ``retries`` is exhausted.

        Returns:
            ``(advanced_progress, all_synced)``. The advanced ``Progress`` carries
            the appended ``process_s3``/``process_api`` and any ``process_metas``
            written by :meth:`sync_process`; the caller MUST rebind it (legacy
            accumulates these in the one shared dict, 1215/1223/1566-1576).
        """
        s3_unf, api_unf = prog.list_unfinished_procs()
        retry_count = 0
        while s3_unf or api_unf:
            if retry_count >= retries:
                break
            prog = await self.sync_process(prog, force=True, exp_yml=exp_yml)
            s3_unf, api_unf = prog.list_unfinished_procs()
            retry_count += 1
        if s3_unf or api_unf:
            LOGGER.info(f"Processes in {exp_yml} did not sync after {retries} tries.")
            return prog, False
        return prog, True

    async def update_process(self, act_yml: Path, act_meta: dict) -> Progress:
        """Fold a finished action into its parent experiment's processes.

        Reads the parent experiment yml + its ``.prg`` via storage, calls the
        pure :func:`fold_action_into_process`, writes the prg back, then pushes
        any newly-completable processes (legacy 1354-1502 machinery; the pure
        logic lives in ``process_fold``).

        Args:
            act_yml: The finished action's yml path.
            act_meta: The action metadata dict.

        Returns:
            The updated experiment ``Progress``.
        """
        act_yml = Path(act_yml)
        exp_yml = self._parent_yml(act_yml, "exp")
        exp_meta = self.sync_storage.read_yml(exp_yml)
        exp_prog = self.get_progress(exp_yml)
        new_dict = fold_action_into_process(
            exp_meta, exp_prog.to_dict(), act_meta, gen_uuid=self.gen_uuid
        )
        exp_prog = Progress.from_dict(exp_prog.yml_relpath, new_dict)
        self._write_progress(exp_yml, exp_prog)
        return await self.sync_process(exp_prog, exp_yml=exp_yml)

    async def sync_process(
        self, exp_prog: Progress, force: bool = False, exp_yml: Optional[Path] = None
    ) -> Progress:
        """Push completable experiment process groups to S3 + API (legacy 1504-1577).

        Uses :func:`should_push_process` to gate each unfinished group, uploads
        the process doc through ``cloud_sink``, and records the S3/API success in
        the prg ``process_s3``/``process_api`` lists.

        Args:
            exp_prog: The experiment progress to advance.
            force: Push even if completion conditions aren't met.
            exp_yml: The experiment yml path (for prg persistence).

        Returns:
            The (possibly advanced) experiment ``Progress``.
        """
        d = exp_prog.to_dict()
        s3_unf, api_unf = exp_prog.list_unfinished_procs()
        is_legacy = bool(d.get("legacy_experiment"))
        groups = d.get("process_groups", {})
        actions_done = d.get("process_actions_done", {})
        finisher_idxs = d.get("legacy_finisher_idxs", [])
        metas = d.get("process_metas", {})

        for pidx in s3_unf:
            if not should_push_process(
                pidx, groups, actions_done, is_legacy, finisher_idxs, force,
                process_metas=metas,
            ):
                continue
            if pidx not in metas:
                continue
            model = metas[pidx]
            uuid_key = model["process_uuid"]
            ok = await self.cloud_sink.upload_bytes(
                _json_bytes(model), f"process/{uuid_key}.json"
            )
            if ok:
                d["process_s3"].append(pidx)
                exp_prog = Progress.from_dict(exp_prog.yml_relpath, d)
                if exp_yml is not None:
                    self._write_progress(exp_yml, exp_prog)

        for pidx in api_unf:
            gids = groups.get(pidx, [])
            if all(i in actions_done for i in gids) and pidx in metas:
                ok = await self.cloud_sink.register_api(metas[pidx], "process")
                if ok:
                    d["process_api"].append(pidx)
                    exp_prog = Progress.from_dict(exp_prog.yml_relpath, d)
                    if exp_yml is not None:
                        self._write_progress(exp_yml, exp_prog)
        return exp_prog

    def _parent_yml(self, child_yml: Path, parent_abbr: str) -> Path:
        """Resolve the parent (exp/seq) yml path for a child yml on disk.

        The parent yml lives one directory up. ``update_process`` runs AFTER the
        contributing action has moved to RUNS_SYNCED while the parent experiment
        usually still lives under RUNS_FINISHED, so the parent dir is searched in
        every status tree (FINISHED/SYNCED/ACTIVE) for the matching
        ``-{parent_abbr}.yml`` -- whichever tree currently holds it wins.
        """
        child_yml = Path(child_yml)
        parent_dir = child_yml.parent.parent  # the experiment/sequence dir
        # ``list_children`` globs ``<dir>/*/*.yml`` (one level DOWN), so to find
        # the parent yml that lives *in* ``parent_dir`` we list children of its
        # grandparent and keep the ``-{abbr}.yml`` whose own dir is ``parent_dir``.
        grandparent = parent_dir.parent
        for tree_dir in (
            Path(syncpaths.finished_path(grandparent)),
            Path(syncpaths.synced_path(grandparent)),
            Path(syncpaths.active_path(grandparent)),
        ):
            want_parent = Path(syncpaths.rename_status(
                parent_dir, syncpaths.status_of(tree_dir)
            ))
            for cand in self.sync_storage.list_children(tree_dir):
                cand = Path(cand)
                if cand.stem.endswith(f"-{parent_abbr}") and cand.parent == want_parent:
                    return cand
        raise FileNotFoundError(f"no -{parent_abbr}.yml parent for {child_yml}")

    # --- bulk / maintenance -------------------------------------------------

    async def finish_pending(
        self, omit_manual_exps: bool = True, actions_first: bool = False
    ) -> list:
        """Enqueue every pending sequence (and optionally acts/exps first).

        Mirrors legacy 1710-1756: lists pending nodes under ``RUNS_FINISHED`` via
        ``sync_storage.list_pending`` and enqueues them. When ``actions_first``,
        actions (rank 0) and experiments (rank 1) are enqueued before sequences
        (rank 2) to drain a partial sync.

        Returns:
            The list of pending sequence paths enqueued.
        """
        finished_root = self._finished_root()
        if actions_first:
            for pp in self.sync_storage.list_pending(finished_root, "act", omit_manual_exps):
                await self.enqueue_yml(pp, rank=0)
            for pp in self.sync_storage.list_pending(finished_root, "exp", omit_manual_exps):
                await self.enqueue_yml(pp, rank=1)
        pending_seqs = list(
            self.sync_storage.list_pending(finished_root, "seq", omit_manual_exps)
        )
        for pp in pending_seqs:
            await self.enqueue_yml(pp, rank=2)
        return pending_seqs

    def reset_sync(self, sync_path: str) -> bool:
        """Revert a synced sequence dir back to ``RUNS_FINISHED`` (legacy 1758-1877).

        Delegates the actual file shuffling to :meth:`unsync_dir`; only operates
        on a path under ``RUNS_SYNCED`` (legacy gate). Returns ``True`` on a
        successful reset, ``False`` otherwise.
        """
        p = Path(sync_path)
        if not self.sync_storage.exists(p):
            LOGGER.info(f"{sync_path} does not exist.")
            return False
        if "RUNS_SYNCED" not in str(sync_path):
            LOGGER.info(f"Cannot reset path not in RUNS_SYNCED: {sync_path}")
            return False
        self.unsync_dir(sync_path)
        return True

    def unsync_dir(self, sync_dir: str) -> None:
        """Move ``sync_dir`` contents SYNCED->FINISHED (legacy 1883-1896).

        Uses ``sync_storage.revert_to_finished`` for the path math + move and
        removes any ``.prg``/``.lock`` sidecars encountered.
        """
        p = Path(sync_dir)
        self.sync_storage.revert_to_finished(p)
        LOGGER.warning(f"Reverted {sync_dir}")

    def cleanup_root(self, root_path: str) -> None:
        """Prune empty week/date dirs under ``RUNS_ACTIVE``/``RUNS_FINISHED`` (legacy 775-808).

        Delegates the empty-dir removal to ``sync_storage.cleanup_empty``.
        """
        for run_kind in ("RUNS_ACTIVE", "RUNS_FINISHED"):
            base = Path(root_path) / run_kind
            if self.sync_storage.exists(base):
                self.sync_storage.cleanup_empty(base)

    def _finished_root(self) -> Path:
        """Resolve the ``RUNS_FINISHED`` root from ``helaodirs`` / config."""
        save_root = getattr(self.helaodirs, "save_root", None)
        if save_root is not None:
            return Path(str(save_root).replace("RUNS_ACTIVE", "RUNS_FINISHED"))
        return Path(self.config.get("root", ".")) / "RUNS_FINISHED"


def _json_bytes(payload: dict) -> bytes:
    """Serialize ``payload`` to canonical JSON bytes for cloud upload."""
    import json

    return json.dumps(payload, default=str).encode("utf-8")
