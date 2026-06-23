"""SyncEngine: stateful sync coordinator injected with SyncStorage."""
import asyncio
import json
from pathlib import Path

from helao.framework.domain.sync.sync_models import HelaoYml, Progress, SyncJob
from helao.framework.ports.sync_storage import SyncStorage
from helao.framework.support.async_utils import AsyncRWLock


class SyncEngine:
    """Orchestrates RUNS_FINISHED → RUNS_SYNCED moves for one server root.

    Injected with a SyncStorage at construction; owns per-sequence AsyncRWLock
    instances and a Progress cache. All filesystem I/O goes through the port.
    """

    def __init__(self, storage: SyncStorage, config: dict) -> None:
        """
        config keys:
          use_s3 (bool): enable cloud upload (default False)
          s3_prefix (str): S3 key prefix
          runs_finished_root (Path): RUNS_FINISHED root directory
          runs_synced_root (Path): RUNS_SYNCED root directory
        """
        self.storage = storage
        self.config = config
        self._seq_locks: dict[str, AsyncRWLock] = {}
        self._progress_cache: dict[str, Progress] = {}

    # ── private helpers ───────────────────────────────────────────────────

    def _get_seq_lock(self, seq_key: str) -> AsyncRWLock:
        if seq_key not in self._seq_locks:
            self._seq_locks[seq_key] = AsyncRWLock()
        return self._seq_locks[seq_key]

    def _seq_key(self, yml: HelaoYml) -> str:
        """First directory component after the RUNS_* dir (the sequence folder name)."""
        parts = list(yml.path.parts)
        for i, part in enumerate(parts):
            if part.startswith("RUNS_"):
                return parts[i + 1] if i + 1 < len(parts) else str(yml.path)
        return str(yml.path)

    def _make_job(self, yml_path: Path) -> SyncJob:
        yml = HelaoYml(yml_path)
        prg_dict = self.storage.read_prg(yml.prg_path)
        progress = Progress.from_dict(prg_dict)
        priority = {"action": 0, "experiment": 1, "sequence": 2}.get(yml.type, 0)
        return SyncJob(yml=yml, progress=progress, priority=priority)

    # ── discovery ─────────────────────────────────────────────────────────

    def list_pending(self, omit_manual: bool = True) -> list[SyncJob]:
        """Return SyncJobs for all *-seq.yml files under runs_finished_root."""
        root = Path(self.config["runs_finished_root"])
        paths = [p for p in self.storage.list_ymls(root) if p.stem.endswith("-seq")]
        if omit_manual:
            paths = [p for p in paths if "manual_orch_seq" not in str(p)]
        return sorted(self._make_job(p) for p in paths)

    def list_pending_acts(self, omit_manual: bool = True) -> list[SyncJob]:
        """Return SyncJobs for all *-act.yml files under runs_finished_root."""
        root = Path(self.config["runs_finished_root"])
        paths = [p for p in self.storage.list_ymls(root) if p.stem.endswith("-act")]
        if omit_manual:
            paths = [p for p in paths if "manual_orch_seq" not in str(p)]
        return sorted(self._make_job(p) for p in paths)

    def list_pending_exps(self, omit_manual: bool = True) -> list[SyncJob]:
        """Return SyncJobs for all *-exp.yml files under runs_finished_root."""
        root = Path(self.config["runs_finished_root"])
        paths = [p for p in self.storage.list_ymls(root) if p.stem.endswith("-exp")]
        if omit_manual:
            paths = [p for p in paths if "manual_orch_seq" not in str(p)]
        return sorted(self._make_job(p) for p in paths)

    # ── progress cache ────────────────────────────────────────────────────

    def get_progress(self, yml_path: Path) -> Progress:
        """Return Progress for yml_path; read from storage on first call, then cache."""
        key = yml_path.name
        if key not in self._progress_cache:
            prg_dict = self.storage.read_prg(HelaoYml(yml_path).prg_path)
            self._progress_cache[key] = Progress.from_dict(prg_dict)
        return self._progress_cache[key]

    # ── core sync ─────────────────────────────────────────────────────────

    async def sync_one(self, job: SyncJob) -> SyncJob:
        """Sync one yml: (upload if use_s3) → move_tree → (zip if seq) → write_prg."""
        seq_key = self._seq_key(job.yml)
        lock = self._get_seq_lock(seq_key)
        is_seq = job.yml.type == "sequence"
        lock_ctx = lock.write_locked() if is_seq else lock.read_locked()

        async with lock_ctx:
            # Yield to the event loop so concurrent coroutines can acquire
            # read locks before any single coroutine monopolises the thread.
            await asyncio.sleep(0)
            new_s3_done = job.progress.s3_done
            if self.config.get("use_s3", False):
                yml_meta = self.storage.read_yml(job.yml.path)
                s3_prefix = self.config.get("s3_prefix", "")
                s3_key = f"{s3_prefix}/{job.yml.relative_path}"
                self.storage.upload_bytes(
                    json.dumps(yml_meta).encode(),
                    s3_key,
                    "application/json",
                )
                new_s3_done = True

            src_dir = job.yml.path.parent
            dst_dir = job.yml.synced_path.parent
            self.storage.move_tree(src_dir, dst_dir)

            if is_seq:
                self.storage.zip_dir(dst_dir)

            new_progress = Progress(
                s3_done=new_s3_done,
                api_done=job.progress.api_done,
                proc_states=job.progress.proc_states,
            )
            self.storage.write_prg(
                job.yml.prg_path,
                new_progress.to_dict(str(job.yml.path)),
            )
            self._progress_cache.pop(job.yml.path.name, None)

        return SyncJob(yml=job.yml, progress=new_progress, priority=job.priority)

    async def update_process(self, act_job: SyncJob) -> SyncJob:
        """Patch process records after an action syncs. No-op in SP6 scope."""
        return act_job

    # ── state management ──────────────────────────────────────────────────

    def reset_sync(self, sync_path: Path) -> bool:
        """Revert a directory from RUNS_SYNCED back to RUNS_FINISHED."""
        try:
            finished_path = Path(str(sync_path).replace("RUNS_SYNCED", "RUNS_FINISHED"))
            self.storage.move_tree(sync_path, finished_path)
            for prg in self.storage.list_files(sync_path, "*.prg"):
                self.storage.remove_prg(prg)
            return True
        except Exception:
            return False

    def unsync_dir(self, sync_dir: Path) -> None:
        """Revert all ymls under sync_dir to RUNS_FINISHED."""
        for yml_path in self.storage.list_ymls(sync_dir):
            self.reset_sync(yml_path.parent)

    def cleanup_root(self, root: Path) -> None:
        """Remove empty directories under root."""
        ymls = self.storage.list_ymls(root)
        dirs = sorted(
            {p.parent for p in ymls},
            key=lambda x: len(x.parts),
            reverse=True,
        )
        for d in dirs:
            self.storage.try_remove_empty(d)
