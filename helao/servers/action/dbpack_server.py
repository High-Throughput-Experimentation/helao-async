# shell: uvicorn motion_server:app --reload
""" Data packaging server

The data packaging server collates finished actions into processes.
Finished actions which do not contribute process information are pushed to 
"""

__all__ = ["makeApp"]

from helao.servers.base import makeActionServ
from helao.drivers.data.dbpack_driver import DBPack
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, servKey, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = makeActionServ(
        config=config,
        server_key=servKey,
        server_title=servKey,
        description="Data packaging server",
        version=0.1,
        driver_class=DBPack,
    )

    @app.post(f"/finish_yml")
    async def finish_yml(yml_path: str):
        await app.driver.add_yml_task(yml_path)
        return yml_path

    @app.post(f"/finish_pending")
    async def finish_pending():
        pending_dict = await app.driver.finish_pending()
        return pending_dict

    @app.post(f"/list_pending")
    def list_pending():
        pending_dict = app.driver.list_pending()
        return pending_dict
        
    return app
