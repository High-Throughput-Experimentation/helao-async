"""Simulated data-packaging server for golden-master capture (spec §6.3, D5).

Hosts the REAL :class:`HelaoSyncer` with ``aws_bucket`` set and no
``aws_config_path``, so the full RUNS_FINISHED -> RUNS_SYNCED -> S3 sync leg
runs on Linux without AWS credentials. Two modes, selected by the server's
``params``:

- local-only (default): ``SyncDriver.to_s3`` returns True with ``self.s3``
  unset — sync completes locally (Q3 verification target).
- recording (``s3_record: true``): a duck-typed S3 client records every
  upload to ``<root>/S3_SIM/<bucket>/<key>`` and logs a manifest line, so
  the harness diffs S3 key templates + payload shapes (§5.6). The same
  recorder object later serves the hexagon syncer, recording both stacks
  identically.

No legacy patch is needed: ``SyncDriver`` leaves ``self.s3 = None`` without
``aws_config_path``, only calls ``self.s3.upload_fileobj(fileobj, bucket,
key)`` / ``self.s3.upload_file(filename, bucket, key)`` from a worker thread
(``asyncio.to_thread`` — sync_driver.py:1776), and never uses ``self.s3r``
beyond assignment, so post-construction injection is sufficient and
behavior-identical when ``s3_record`` is unset.

Endpoint surface mirrors the hte dbpack_server verbatim so ``move_dir``'s
``/finish_yml`` handoff and the harness quiesce polls (``/n_queue`` +
``/tasks``) work unmodified. Windows-tolerant (pathlib only) so at-station
captures (§6.6) can wire the same server.
"""

__all__ = ["makeApp"]

import json
import shutil
import threading
from pathlib import Path

from helao.core.servers.base_api import BaseAPI
from helao.core.drivers.data.sync_driver import HelaoSyncer


class RecordingS3Client:
    """Duck-typed stand-in for the boto3 S3 client surface SyncDriver uses.

    Both methods are called via ``asyncio.to_thread`` and must be
    thread-safe; a lock serializes manifest appends.
    """

    def __init__(self, sim_root: Path):
        self.sim_root = Path(sim_root)
        self.manifest_path = self.sim_root / "manifest.jsonl"
        self._lock = threading.Lock()
        self.sim_root.mkdir(parents=True, exist_ok=True)

    def _record(self, bucket: str, key: str, mode: str) -> None:
        entry = {
            "bucket": bucket,
            "key": key,
            "mode": mode,
            "gzip": key.endswith(".gz"),
        }
        with self._lock:
            with open(self.manifest_path, "a") as f:
                f.write(json.dumps(entry) + "\n")

    def upload_fileobj(self, fileobj, bucket: str, key: str, **kwargs) -> None:
        dest = self.sim_root / bucket / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            shutil.copyfileobj(fileobj, f)
        self._record(bucket, key, "fileobj")

    def upload_file(self, filename, bucket: str, key: str, **kwargs) -> None:
        dest = self.sim_root / bucket / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(filename), dest)
        self._record(bucket, key, "file")


class SimHelaoSyncer(HelaoSyncer):
    """HelaoSyncer that swaps in the recorder when ``params.s3_record`` is set."""

    def __init__(self, action_serv):
        super().__init__(action_serv)
        if self.config_dict.get("s3_record", False):
            sim_root = Path(action_serv.helaodirs.root) / "S3_SIM"
            self.s3 = RecordingS3Client(sim_root)


def makeApp(server_key) -> BaseAPI:
    """Build the sim data-packaging FastAPI app (dbpack surface, sim syncer)."""

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Simulated data packaging server (golden capture)",
        version=0.1,
        driver_classes=[SimHelaoSyncer],
    )

    @app.post("/finish_yml", tags=["private"])
    async def finish_yml(yml_path: str) -> str:
        """Enqueue a finished YAML for sync (rank by -seq/-exp/-act suffix)."""
        clean_path = yml_path.strip('"').strip("'")
        if clean_path.endswith("-seq.yml"):
            rank = 2
        elif clean_path.endswith("-exp.yml"):
            rank = 1
        elif clean_path.endswith("-act.yml"):
            rank = 0
        else:
            rank = -1
        await app.driver.enqueue_yml(clean_path, rank)
        return yml_path

    @app.post("/list_pending", tags=["private"])
    def list_pending():
        """List sequence YAML files in RUNS_FINISHED awaiting sync."""
        return app.driver.list_pending()

    @app.post("/finish_pending", tags=["private"])
    async def finish_pending(actions_first: bool = True):
        """Discover RUNS_FINISHED YAML files and enqueue them for sync."""
        return await app.driver.finish_pending(actions_first=actions_first)

    @app.post("/reset_sync", tags=["private"])
    def reset_sync(sync_path: str) -> str:
        """Reset a synced sequence zip or partially-synced folder for re-sync."""
        app.driver.reset_sync(sync_path.strip('"').strip("'"))
        return sync_path

    @app.post("/tasks", tags=["private"])
    async def running() -> dict:
        """Return identifiers of running sync tasks and the queued count."""
        return {
            "running": list(app.driver.running_tasks.keys()),
            "num_queued": (app.driver.task_queue.qsize()),
        }

    @app.post("/list_exceptions", tags=["private"])
    async def list_exceptions() -> dict:
        """Return exceptions captured on currently running sync tasks."""
        return {k: d.exception() for k, d in app.driver.running_tasks.items()}

    @app.post("/n_queue", tags=["private"])
    async def n_queue() -> int:
        """Return the number of items waiting in the sync task queue."""
        return app.driver.task_queue.qsize()

    @app.post("/current_progress", tags=["private"])
    async def current_progress():
        """Return the syncer's progress dictionary."""
        return app.driver.progress

    return app
