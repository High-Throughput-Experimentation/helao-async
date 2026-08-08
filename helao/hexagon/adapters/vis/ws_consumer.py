"""The hexagon's status-stream consumer faces (P7c, Amendment §8).

Two things live here, one per port declared in ``ports/status.py``:

- :class:`WsConsumer` -- :class:`~helao.hexagon.ports.status.StatusStreamPort`
  over the real :class:`~helao.helpers.ws_utils.WsSubscriber`. It covers
  consumer faces 1 *and* 2 (Bokeh's WsPublisher routes and the ``_ws_relay``
  streams): the transport decode is one and the same
  ``pickle.loads(pyzstd.decompress(...))``, and only the producer differs.
  Nothing is re-implemented here -- wrapping the real subscriber is the point,
  since a second decoder is exactly the drift this slice's frames test for.
- :data:`CHANNEL_NORMALIZERS` -- the conformance declaration for face 3: the
  two ``ingest`` normalizers, keyed by ``ws_path`` and *typed* as
  :class:`~helao.hexagon.ports.status.ChannelNormalizerPort`, so a signature
  drift in either one is a type error here rather than a blank panel at a
  station.

This module is under ``adapters/vis/``, not ``adapters/native/``: the native
layer may not import ``helao.core.servers.*`` (test_boundaries.py:131-143),
and the Reflex ingest layer is exactly that.
"""

import asyncio
import contextlib

from helao.core.servers.reflex.ingest import normalize, normalize_data_package
from helao.helpers.ws_utils import WsSubscriber
from helao.hexagon.ports.status import (
    CHANNELS,
    ChannelNormalizerPort,
    StatusStreamPort,
)

__all__ = ["CHANNEL_NORMALIZERS", "WsConsumer"]

#: Face 3, declared against the port. Mirrors ``ingest.NORMALIZERS`` (asserted
#: equal in ``test_status_consumer_faces.py``) rather than replacing it -- the
#: Reflex stack keeps reading its own map; this one exists so the hexagon's
#: seam is the thing that type-checks.
CHANNEL_NORMALIZERS: dict[str, ChannelNormalizerPort] = {
    # No ws_status entry, deliberately: no Reflex consumer of /ws_status
    # exists (ingest.VIS_KEY_TO_WS_PATH maps only live_vis/action_vis).
    # Adding one is a deliberate act that must also update the test pinning
    # this absence.
    "ws_live": normalize,
    "ws_data": normalize_data_package,
}


class WsConsumer:
    """:class:`StatusStreamPort` backed by :class:`WsSubscriber`.

    Stateless: each :meth:`subscribe` returns its own subscriber, so one
    consumer instance can serve every ``(server, channel)`` a process reads.
    """

    def subscribe(self, host: str, port: int, channel: str) -> object:
        """Open a subscription to ``ws://host:port/<channel>``.

        Raises:
            ValueError: If ``channel`` is not one of
                :data:`~helao.hexagon.ports.status.CHANNELS`. Worth failing
                loudly on: ``WsSubscriber`` retries a bad path indefinitely
                with capped backoff, so a typo yields a permanently empty
                panel and a warning line every 30 s, never an error.
        """
        if channel not in CHANNELS:
            raise ValueError(
                f"unknown status channel {channel!r}; expected one of {CHANNELS}"
            )
        return WsSubscriber(host, port, channel)

    async def read(self, subscription: object) -> list:
        """Drain everything buffered on ``subscription`` since the last read."""
        return await subscription.read_messages()  # type: ignore[attr-defined]

    async def close(self, subscription: object) -> None:
        """Cancel the subscriber's background task and await its exit.

        ``WsSubscriber`` has no close method of its own -- its loop ends only
        on cancellation (``CancelledError`` is deliberately not caught there),
        so the teardown belongs on this side of the seam.
        """
        task = subscription.subscriber_task  # type: ignore[attr-defined]
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


_PORT_CONFORMANCE: StatusStreamPort = WsConsumer()
