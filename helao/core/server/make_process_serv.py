
__all__ = ["make_process_serv"]

from fastapi import WebSocket

from .api import HelaoFastAPI
from .base import Base


def make_process_serv(
    config, server_key, server_title, description, version, driver_class=None
):
    app = HelaoFastAPI(
        config, server_key, title=server_title, description=description, version=version
    )

    @app.on_event("startup")
    def startup_event():
        app.base = Base(app)
        if driver_class:
            app.driver = driver_class(app.base)

    @app.websocket("/ws_status")
    async def websocket_status(websocket: WebSocket):
        """Broadcast status messages.

        Args:
        websocket: a fastapi.WebSocket object
        """
        await app.base.ws_status(websocket)

    @app.websocket("/ws_data")
    async def websocket_data(websocket: WebSocket):
        """Broadcast status dicts.

        Args:
        websocket: a fastapi.WebSocket object
        """
        await app.base.ws_data(websocket)

    @app.post("/get_status")
    def status_wrapper():
        return app.base.status

    @app.post("/attach_client")
    async def attach_client(client_servkey: str):
        return await app.base.attach_client(client_servkey)

    @app.post("/endpoints")
    def get_all_urls():
        """Return a list of all endpoints on this server."""
        return app.base.get_endpoint_urls(app)

    return app
