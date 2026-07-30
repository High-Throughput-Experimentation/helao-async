"""Live-buffer collaborator extracted from ``Base`` (CARDS P6, Stage S1).

``Base.live_buffer_task``/``_stamp_lbuf_dict``/``put_lbuf``/``put_lbuf_nowait``/
``get_lbuf``/``get_realtime``/``get_realtime_nowait`` implement the "live
buffer" cluster: a background task that drains ``live_q`` into the
``live_buffer`` dict, timestamped writers into that queue, a reader for the
dict, and the NTP-corrected real-time helpers used to stamp HLO headers. This
module moves those seven method bodies into a ``LiveBuffer`` collaborator that
``Base`` delegates to.

This is the FIRST ``Base`` collaborator (CARDS P6 S1); it establishes the
``Base._init_collaborators()`` seam that later P6 stages reuse (mirrors
``Orch._init_collaborators`` from CARDS P5).

Per the P5 constraints (same rule applied here for ``Base``): ``LiveBuffer``
caches no shared mutable state -- it holds only the ``base`` back-reference
and reads/writes ``live_q``/``live_buffer``/``ntp_offset`` through it at call
time. Those attributes stay on ``Base`` (constructed exactly where they are
today in ``Base.__init__``); this collaborator only relocates the method
bodies. Behavior is byte-identical to the original inline methods.

Note: ``Active`` has its own, distinct ``get_realtime``/``get_realtime_nowait``
methods (a thin forward to ``self.base.get_realtime``/``get_realtime_nowait``)
-- those stay on ``Active`` and are untouched by this module.

Lock/queue ownership map (Base-server data-plane; duplicated verbatim in
``base_status.py``, ``base_live_buffer.py``, and ``active_data_stream.py`` --
the three queue owners):

- ``status_q`` (on ``Base``) -- written by ``StatusBroadcaster`` (status
  packages) + ``Active.add_status``; subscribed by
  ``StatusBroadcaster.ws_status``.
- ``live_q`` (on ``Base``) -- written by ``LiveBuffer.put_lbuf``; drained by
  ``LiveBuffer.live_buffer_task``; relayed by ``StatusBroadcaster.ws_live``.
- ``data_q`` (on ``Base``) -- written by ``DataStreamer.enqueue_data*`` (via
  ``Active``); drained by ``DataStreamer.log_data_task``; relayed by
  ``StatusBroadcaster.ws_data``.
- Active per-action collaborators (``data_file_writer``/``data_stream``/
  ``executor_runner``/``action_finalizer``) hold only ``self.active``; Base
  collaborators hold only ``self.base``; all read shared state at call time.
"""

from time import time

import numpy as np

from helao.core.servers.base_primitives import Timer
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class LiveBuffer:
    """Live-buffer methods for a ``Base``.

    Holds only the ``base`` back-reference (never a cached queue/dict/offset),
    per the call-time state resolution rule -- see module docstring.
    """

    def __init__(self, base):
        self.base = base

    async def live_buffer_task(self):
        """Subscribe to the live queue and fold every published message into ``live_buffer``."""
        base = self.base
        LOGGER.info(f"{base.server.server_name} live buffer task created.")
        async for live_msg in base.live_q.subscribe():
            base.live_buffer.update(live_msg)

    @staticmethod
    def _stamp_lbuf_dict(live_dict: dict) -> dict:
        """Wrap each value in a ``(value, now())`` tuple for the live buffer."""
        return {k: (v, time()) for k, v in live_dict.items()}

    async def put_lbuf(self, live_dict: dict) -> None:
        """Timestamp ``live_dict`` and publish it to the live queue (awaited put)."""
        base = self.base
        await base.live_q.put(base._stamp_lbuf_dict(live_dict))

    def put_lbuf_nowait(self, live_dict: dict) -> None:
        """Timestamp ``live_dict`` and publish it to the live queue without awaiting."""
        base = self.base
        base.live_q.put_nowait(base._stamp_lbuf_dict(live_dict))

    def get_lbuf(self, live_key):
        """Return the most recent ``(value, timestamp)`` tuple stored under ``live_key``."""
        base = self.base
        return base.live_buffer[live_key]

    async def get_realtime(self, epoch_ns=None, offset=None) -> int:
        """Asynchronous wrapper around :meth:`get_realtime_nowait`.

        Args:
            epoch_ns: Optional epoch time in nanoseconds; defaults to now.
            offset: Optional clock offset in seconds; defaults to ``ntp_offset``.

        Returns:
            NTP-corrected wall-clock time in nanoseconds.
        """
        base = self.base
        return base.get_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

    def get_realtime_nowait(self, epoch_ns=None, offset=None) -> int:
        """Return the wall-clock time in nanoseconds, optionally with a custom offset.

        Args:
            epoch_ns: Optional epoch time in nanoseconds; defaults to now.
            offset: Optional clock offset in seconds; defaults to ``ntp_offset``.

        Returns:
            NTP-corrected wall-clock time in nanoseconds.
        """
        base = self.base
        if offset is None:
            if base.ntp_offset is not None:
                offset_ns = int(np.floor(base.ntp_offset * 1e9))
            else:
                offset_ns = 0
        else:
            offset_ns = int(np.floor(offset * 1e9))
        if epoch_ns is None:
            timer = Timer()
            real_time = timer.time_ns() + offset_ns
        else:
            real_time = epoch_ns + offset_ns
        return int(np.floor(real_time))
