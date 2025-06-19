# shell: uvicorn motion_server:app --reload
""" Data packaging server

The data packaging server collates finished actions into processes.
Finished actions which do not contribute process information are pushed to 
"""

__all__ = ["makeApp"]

from helao.servers.base_api import BaseAPI
from helao.drivers.data.sync_driver import HelaoSyncer
from helao.helpers.config_loader import CONFIG


def makeApp(server_key):
    config = CONFIG

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Data packaging server",
        version=0.1,
        driver_classes=[HelaoSyncer],
    )

    @app.post("/finish_yml", tags=["private"])
    async def finish_yml(yml_path: str):
        """Pushes HELAO data to S3/API and moves files to RUNS_SYNCED."""
        await app.driver.enqueue_yml(yml_path.strip('"').strip("'"))
        return yml_path

    @app.post("/list_pending", tags=["private"])
    def list_pending():
        """Finds sequence ymls in RUNS_FINISHED."""
        return app.driver.list_pending()

    @app.post("/finish_pending", tags=["private"])
    async def finish_pending():
        """Finds and queues sequence ymls from RUNS_FINISHED."""
        return await app.driver.finish_pending()

    @app.post("/reset_sync", tags=["private"])
    def reset_sync(sync_path: str):
        """Resets a synced sequence zip or partially-synced folder."""
        app.driver.reset_sync(sync_path.strip('"').strip("'"))
        return sync_path

    @app.post("/tasks", tags=["private"])
    async def running():
        """Num running sync tasks."""
        return {
            "running": list(app.driver.running_tasks.keys()),
            "num_queued": (app.driver.task_queue.qsize()),
        }

    @app.post("/list_exceptions", tags=["private"])
    async def list_exceptions():
        """Get exceptions from running tasks."""
        return {k: d.exception() for k, d in app.driver.running_tasks.items()}

    @app.post("/n_queue", tags=["private"])
    async def n_queue():
        """Get number of enqueued sync tasks."""
        return app.driver.task_queue.qsize()

    @app.post("/current_progress", tags=["private"])
    async def current_progress():
        return app.driver.progress

    return app
