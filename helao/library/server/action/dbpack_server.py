# shell: uvicorn motion_server:app --reload
""" Data packaging server

The data packaging server collates finished actions into processes.
Finished actions which do not contribute process information are pushed to 
"""

__all__ = ["makeApp"]

from helaocore.server.base import makeActionServ
from helao.library.driver.dbpack_driver import DBPack
from helaocore.helper.config_loader import config_loader


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
        progress = await app.driver.finish_yml(yml_path)
        return progress

    @app.post(f"/finish_pending")
    async def finish_pending():
        pending_dict = await app.driver.finish_pending()
        return pending_dict

    @app.post(f"/list_pending")
    def list_pending():
        pending_dict = app.driver.list_pending()
        return pending_dict
        
    @app.post("/shutdown")
    def post_shutdown():
        pass

    @app.on_event("shutdown")
    def shutdown_event():
        # this code doesn't run
        pass

    return app
