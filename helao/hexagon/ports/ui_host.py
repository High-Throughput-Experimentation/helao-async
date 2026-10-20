"""UI-host port (spec §4.5; Amendment §6, D6 generalized): nothing outside
the app layer may construct a UI-hosting server. ``start_document_host``/``stop``
are a Bokeh-shaped document-server host (today's only consumer: the Galil
plate-aligner, ``adapters/vis/galil_aligner_host.py``, folding in the standing
D6 exception noted in master spec §4.4).

Ports may import only ``helao.hexagon.domain.*``/``helao.hexagon.ports.*``/
``helao.core.drivers.helao_driver`` (test_boundaries.py:78-82), so every
member here returns ``object`` -- no bokeh/reflex name ever appears in this
module. The real construction lives in ``app/ui_host.py``, the one place
this rule permits ``bokeh.server`` to be imported.
"""

from collections.abc import Callable
from typing import Any, Optional, Protocol, runtime_checkable

__all__ = ["UiHostPort"]


@runtime_checkable
class UiHostPort(Protocol):
    def start_document_host(
        self,
        routes: dict[str, Callable[[Any], Any]],
        host: str,
        port: int,
        allow_websocket_origin: Optional[list[str]] = None,
    ) -> object:
        """Start a document-serving UI host and return an opaque handle.

        ``routes`` maps a URL path to a document-factory callable (mirrors
        Bokeh's ``Server({path: factory}, ...)`` shape without naming Bokeh
        here). Callers hold the returned handle only to pass back to
        :meth:`stop` -- they must never inspect its type.
        """
        ...

    def stop(self, handle: object) -> None:
        """Stop a host previously returned by :meth:`start_document_host`."""
        ...
