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

from collections.abc import Callable
from typing import Any, Optional

__all__ = ["BokehServerUiHost"]


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

        server = Server(
            routes,
            port=port,
            address=host,
            allow_websocket_origin=allow_websocket_origin or [f"{host}:{port}"],
        )
        server.start()
        return server

    def stop(self, handle: object) -> None:
        handle.stop()  # type: ignore[attr-defined]
