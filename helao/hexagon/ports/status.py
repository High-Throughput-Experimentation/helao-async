"""Status port (spec §4.3.6): push + dual WS stacks + three consumer faces.

Both parallel WS mechanisms survive (consumers exist for each): the
WsPublisher-backed /ws_status /ws_data /ws_live routes AND the _ws_relay
zstd-compressed-pickle streams. Serialization happens ONLY in the adapter
(KEEP #4: _json_clean at the relay). The legacy blocking 0.3 s per-client
pacing is preserved behavior until post-parity.

`StatusPort` above is publish-side. Amendment §8 requires this port to also
enumerate the **consumer** side, because the third consumer class
distinguishes payloads the first two do not:

1. ``bokeh_ws_subscriber`` -- Bokeh visualizers read the WsPublisher routes
   through ``helao.helpers.ws_utils.WsSubscriber``.
2. ``relay_pickle_stream`` -- remote subscribers read the ``_ws_relay``
   zstd-compressed-pickle streams. Same transport decode as (1); a *different
   producer*, so the same route name carries a plain dict here and a typed
   model there (``OrchAPI`` is a sibling of ``BaseAPI``, not a subclass).
   Faces 1 and 2 therefore share one seam, :class:`StatusStreamPort`.
3. ``reflex_ingest_normalizer`` -- the Reflex stack's
   ``helao/ui/reflex/ingest.py`` normalizers, selected **by
   ``ws_path``, not uniformly across channels**: ``ws_live`` relays a
   ``{datalab: (value, epoch)}`` dict while ``ws_data`` carries a pickled
   ``DataPackageModel`` whose samples sit at ``.datamodel.data[key][column]``.
   A single normalizer silently drops the other endpoint's messages with no
   error on either side. That face is :class:`ChannelNormalizerPort`, and the
   channel keying lives with the caller (a ``{ws_path: normalizer}`` map),
   not inside the normalizer -- see the note on its signature.

Ports may import only ``helao.hexagon.domain.*``/``helao.hexagon.ports.*``/
``helao.core.drivers.helao_driver`` (test_boundaries.py:78-82), so the two
consumer Protocols name no vendor type: subscriptions are opaque handles and
decoded payloads are ``object``. The concrete faces live in
``adapters/vis/ws_consumer.py``.
"""

from typing import Protocol, runtime_checkable
from uuid import UUID

from helao.hexagon.domain.models import ActionServerModel

__all__ = [
    "CHANNELS",
    "CONSUMER_FACES",
    "ChannelNormalizerPort",
    "StatusPort",
    "StatusStreamPort",
]

#: The three WS routes every producer family registers and every consumer
#: face reads. Pinned here so a face can be checked against the vocabulary
#: rather than against a string literal at each call site.
CHANNELS: tuple[str, str, str] = ("ws_status", "ws_data", "ws_live")

#: Amendment §8's three consumer faces, mapped to the port each satisfies.
#: Faces 1 and 2 differ in *producer*, not in decode, so they share a seam.
CONSUMER_FACES: dict[str, str] = {
    "bokeh_ws_subscriber": "StatusStreamPort",
    "relay_pickle_stream": "StatusStreamPort",
    "reflex_ingest_normalizer": "ChannelNormalizerPort",
}


@runtime_checkable
class StatusPort(Protocol):
    async def attach_client(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        retry_limit: int = 5,
    ) -> bool: ...

    async def detach_client(
        self, client_servkey: str, client_host: str, client_port: int
    ) -> None: ...

    async def send_status(self, asm: ActionServerModel, retries: int = 5) -> None:
        """POST the full/filtered ActionServerModel to every registered
        client's private /update_status."""
        ...

    async def send_nonblocking_status(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        server_key: str,
        exec_id: str,
        act_uuid: UUID,
        status: str,
        retries: int = 3,
    ) -> None:
        """Nonblocking executors push /update_nonblocking directly."""
        ...

    async def publish_status(self, payload: dict) -> None: ...

    async def publish_data(self, payload: dict) -> None: ...

    async def publish_live(self, payload: dict) -> None: ...


@runtime_checkable
class StatusStreamPort(Protocol):
    """Consumer faces 1+2: read one channel of one server's status stream.

    One seam for both, because the transport decode is identical (the frame
    is a zstd-compressed pickle either way) and only the *producer* differs.
    That is exactly why this port yields ``object``: on ``/ws_status`` the
    base_api family delivers an ``ActionModel`` and the orch_api family a
    plain ``dict``, and a consumer that assumes either one blanks silently
    against the other.
    """

    def subscribe(self, host: str, port: int, channel: str) -> object:
        """Open a subscription to ``channel`` on ``host:port``.

        ``channel`` is one of :data:`CHANNELS`. The return is an opaque
        handle: callers hold it only to pass back to :meth:`read` and
        :meth:`close`, and must never inspect its type.
        """
        ...

    async def read(self, subscription: object) -> list:
        """Drain every payload decoded since the last read, in receipt order.

        Returns a possibly-empty list of ``object`` -- the payload type is the
        producer's business, not this seam's.
        """
        ...

    async def close(self, subscription: object) -> None:
        """Tear down a subscription returned by :meth:`subscribe`."""
        ...


@runtime_checkable
class ChannelNormalizerPort(Protocol):
    """Consumer face 3: turn one channel's decoded payloads into columns+rows.

    **The channel is not a parameter.** A normalizer handles exactly one
    channel and is *selected* by ``ws_path`` upstream (``ingest.NORMALIZERS``
    is a ``{ws_path: normalizer}`` map); the normalizer itself never sees the
    path. Passing the path in would suggest one normalizer could branch on it,
    which is the single-normalizer bug Amendment §8 exists to prevent.

    The concrete faces are ``ingest.normalize`` (``ws_live``) and
    ``ingest.normalize_data_package`` (``ws_data``). The return is a bare
    ``tuple`` -- ``(numeric_columns, mixed_rows)`` at every call site, so
    unpacking is part of the contract, while the *element* types stay
    unnamed: they are a Reflex-stack concern this layer must not import.
    """

    def __call__(self, messages: list) -> tuple: ...
