"""Native sync graft (P2e, D1) — the sync-leg analog of active_graft.py:
instance-level rebinding is the sanctioned wrap seam; NO legacy source is
modified.

What it reroutes: the DB server's ``app.driver``. BaseAPI's own startup
closure (base_api.py:669/:672) constructs the legacy ``SimHelaoSyncer`` and
binds it first; this graft — invoked from the DB shim's startup hook, which
Starlette runs AFTER BaseAPI's — (a) cancels the legacy driver's
``syncer_loops`` worker tasks (orphan fix: ``shutdown()`` is a no-op, a bare
rebind would leak them idle on an empty queue), (b) constructs the raw P2c
``NativeSyncer`` against the live ``Base`` (which satisfies the ``SyncerHost``
duck-type: server_cfg/world_cfg/helaodirs, base.py:142/:148/:177), (c)
replicates ``SimHelaoSyncer.__init__``'s ``RecordingS3Client`` injection
(sim_db_server.py:81-85) when ``params.s3_record`` is set, and (d) rebinds
``app.driver``. Every DB endpoint (sim_db_server.py:111-151) resolves
``app.driver`` at call time, so 100% of sync traffic routes native.

Binds the RAW ``NativeSyncer`` — NOT ``NativeSyncAdapter`` (its
``finish_pending(self)`` drops the ``actions_first`` kwarg the harness posts,
and it exposes no ``running_tasks``/``task_queue`` for ``/tasks``+``/n_queue``).

Must be called with a running event loop: ``SyncDriver.__init__`` spawns the
``max_tasks`` syncer worker tasks (native sync_driver.py:765).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from helao.deploy.test.servers.action.sim_db_server import RecordingS3Client
from helao.helpers import helao_logging as logging
from helao.hexagon.adapters.native.native_syncer import NativeSyncer

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["NativeSyncGraft", "graft_native_sync"]


@dataclass
class NativeSyncGraft:
    app: object
    native: NativeSyncer
    originals: Dict[str, object] = field(default_factory=dict)

    def close(self) -> None:
        """Symmetric unhook: cancel the native worker loops, restore the
        pre-graft driver. Tasks are cancelled, not awaited (shutdown path)."""
        for task in self.native.syncer_loops.values():
            task.cancel()
        self.app.driver = self.originals["driver"]  # type: ignore[attr-defined]


def graft_native_sync(base, params: dict) -> NativeSyncGraft:
    """Rebind the DB server's ``app.driver`` from the legacy SimHelaoSyncer
    to the P2c NativeSyncer. ``base`` is the live legacy ``Base`` (its
    ``.app`` back-ref, base.py:139, reaches the FastAPI app); ``params`` is
    the DB server's local ``server_cfg['params']`` — on the DB server the
    NativeSyncer's world-config fallback resolves to the SAME block, so
    ``params.get('s3_record')`` matches SimHelaoSyncer's post-fallback read.
    """
    app = base.app
    old_driver = getattr(app, "driver", None)
    if old_driver is None:
        raise RuntimeError(
            "sync graft needs the legacy syncer live on app.driver; BaseAPI's "
            "startup has not run (hook order broke) or driver_classes was empty"
        )
    # Orphan fix (D1): BaseAPI startup already spawned the legacy syncer's
    # worker loops; cancel them before the native instance takes over.
    for task in getattr(old_driver, "syncer_loops", {}).values():
        task.cancel()
    native = NativeSyncer(base)
    if params.get("s3_record", False):
        # Replicates SimHelaoSyncer.__init__ (sim_db_server.py:81-85).
        # IMPORT of legacy sim code, not an edit (precedent: factory.py
        # imports helao.deploy.test.* as LEGACY_MODULE).
        native.s3 = RecordingS3Client(Path(base.helaodirs.root) / "S3_SIM")
    graft = NativeSyncGraft(app=app, native=native)
    graft.originals["driver"] = old_driver
    # The DB endpoints resolve app.driver at call time; app.drivers (the
    # namedtuple) intentionally keeps the legacy instance — nothing reads it,
    # and BaseAPI's shutdown hook resolves self.driver (now native; its
    # shutdown() is a no-op on both stacks).
    app.driver = native
    LOGGER.info(
        "hexagon native sync grafted (app.driver -> NativeSyncer; legacy "
        f"{type(old_driver).__name__} syncer_loops cancelled)"
    )
    return graft
