"""``BokehServerUiHost`` (P7d, D6 generalized): the ONLY module in
``helao/hexagon`` that constructs ``bokeh.server.server.Server`` (enforced
by test_boundaries.py's bokeh.server-outside-app/ rule). Every adapter that
needs to host a Bokeh document -- today the Galil plate-aligner
(``adapters/vis/galil_aligner_host.py``) -- receives an instance of this
behind ``ports.ui_host.UiHostPort`` instead of importing ``bokeh.server``
itself.

The import stays lazy inside :meth:`start_document_host`, the same
convention the aligner host used before this fold-in: the module -- and
whatever composes it -- stays importable without a live Bokeh document
context or event loop.
"""

import asyncio
from collections.abc import Callable
from typing import Any, Optional

__all__ = ["BokehServerUiHost", "on_loop_thread"]


def on_loop_thread(
    func: Callable[[Any], Any], loop: asyncio.AbstractEventLoop
) -> Callable[[Any], Any]:
    """Run a Bokeh document factory on ``loop`` (the server's event loop).

    Bokeh 3.10 builds ``FunctionHandler`` documents in a worker thread
    (``asyncio.to_thread``). helao apps start asyncio tasks while building
    the document (``WsSubscriber``, operator backend), which needs a running
    loop, so hop back onto the server's loop. Older Bokeh calls the factory on
    the loop thread already; it then runs directly.
    """

    def wrapped(doc):
        try:
            asyncio.get_running_loop()
        except RuntimeError:

            async def call():
                return func(doc)

            return asyncio.run_coroutine_threadsafe(call(), loop).result()
        return func(doc)

    return wrapped


class BokehServerUiHost:
    """``UiHostPort`` adapter: real ``bokeh.server.server.Server``
    construction lives here and only here."""

    def start_document_host(
        self,
        routes: dict[str, Callable[[Any], Any]],
        host: str,
        port: int,
        allow_websocket_origin: Optional[list[str]] = None,
    ) -> object:
        from bokeh.server.server import Server
        from tornado.ioloop import IOLoop

        # Server(io_loop=None) adopts IOLoop.current() -- the same loop here.
        loop = IOLoop.current().asyncio_loop  # type: ignore[attr-defined]
        server = Server(
            {path: on_loop_thread(f, loop) for path, f in routes.items()},
            port=port,
            address=host,
            allow_websocket_origin=allow_websocket_origin or [f"{host}:{port}"],
        )
        server.start()
        return server

    def stop(self, handle: object) -> None:
        handle.stop()  # type: ignore[attr-defined]
