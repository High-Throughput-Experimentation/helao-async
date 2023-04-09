# shell: uvicorn motion_server:app --reload
""" Data packaging server

The data packaging server collates finished actions into processes.
Finished actions which do not contribute process information are pushed to 
"""

__all__ = ["makeApp"]

from helao.servers.base import HelaoBase
from helao.drivers.data.sync_driver import HelaoSyncer
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, server_key, helao_root):
    config = config_loader(confPrefix, helao_root)

    app = HelaoBase(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Data packaging server",
        version=0.1,
        driver_class=HelaoSyncer,
    )

    @app.post("/finish_yml", tags=["private"])
    async def finish_yml(yml_path: str):
        await app.driver.enqueue_yml(yml_path)
        return yml_path

    @app.post("/running", tags=["private"])
    async def running():
        return list(app.driver.running_tasks.keys())

    @app.post("/list_exceptions", tags=["private"])
    async def list_exceptions():
        return {k: d.exception() for k, d in app.driver.running_tasks.items()}

    @app.post("/n_queue", tags=["private"])
    async def n_queue():
        return app.driver.task_queue.qsize()

    @app.post("/current_progress", tags=["private"])
    async def current_progress():
        return app.driver.progress

    # @app.post("/finish_pending", tags=["private"])
    # async def finish_pending():
    #     pending_dict = await app.driver.finish_pending()
    #     return pending_dict

    # @app.post("/list_pending", tags=["private"])
    # def list_pending():
    #     pending_dict = app.driver.list_pending()
    #     return pending_dict

    return app
