# shell: uvicorn motion_server:app --reload
"""Data packaging server.

Wraps :class:`HelaoSyncer` and exposes private endpoints used by other servers
(and operators) to enqueue finished YAML records for upload to S3 / the API,
inspect the syncer's pending queue and progress, and reset partially synced
runs.
"""

__all__ = ["makeApp"]

from helao.framework.app.base_api import BaseAPI
from helao.core.drivers.data.sync_driver import HelaoSyncer  # seam: framework HelaoSyncer exists (helao.framework.app.sync_driver) but the switch is deferred to DB-server bring-up so it can be verified against real S3 (production data-shipping path)


def makeApp(server_key) -> BaseAPI:
    """Build the data-packaging FastAPI app.

    Constructs a :class:`BaseAPI` backed by :class:`HelaoSyncer` and registers
    the private syncer-management endpoints.

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`BaseAPI` application.
    """

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Data packaging server",
        version=0.1,
        driver_classes=[HelaoSyncer],
    )

    @app.post("/finish_yml", tags=["private"])
    async def finish_yml(yml_path: str) -> str:
        """Enqueue a finished YAML for upload and move to ``RUNS_SYNCED``.

        Determines the rank from the file suffix (``-seq.yml``, ``-exp.yml``,
        ``-act.yml``) and forwards to :meth:`HelaoSyncer.enqueue_yml`.
        """
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
        """List sequence YAML files in ``RUNS_FINISHED`` awaiting sync."""
        return app.driver.list_pending()

    @app.post("/finish_pending", tags=["private"])
    async def finish_pending(actions_first: bool = True):
        """Discover ``RUNS_FINISHED`` YAML files and enqueue them for sync.

        Args:
            actions_first: When ``True`` queue action YAMLs before experiment
                and sequence YAMLs.
        """
        return await app.driver.finish_pending(actions_first=actions_first)

    @app.post("/reset_sync", tags=["private"])
    def reset_sync(sync_path: str) -> str:
        """Reset a synced sequence zip or a partially-synced folder for re-sync."""
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
