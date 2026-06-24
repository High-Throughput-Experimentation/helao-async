"""COM event sinks for streaming dtaq data out of a Gamry potentiostat.

``GamryDtaqSink`` is the active sink wired up to a running dtaq; it cooks
incoming data points in response to ``OnDataAvailable`` / ``OnDataDone``
callbacks. ``DummySink`` is a no-op placeholder used by ``GamryDriver`` when
no measurement is in progress.
"""

from dataclasses import dataclass, field
from typing import Optional

from helao.framework.support import helao_logging as logging  # get LOGGER from BaseAPI instance
LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

class GamryDtaqSink:
    """COM event sink that buffers cooked samples from a running dtaq.

    Attributes:
        dtaq: The GamryCOM dtaq object whose events are being received.
        acquired_points: Accumulated raw data tuples from successive cooks.
        status: ``idle``, ``measuring``, or ``done``.
        buffer_size: Reserved for future use.
    """

    def __init__(self, dtaq):
        """Initialize the sink in the ``idle`` state.

        Args:
            dtaq: GamryCOM dtaq COM object.
        """
        self.dtaq = dtaq
        self.acquired_points = []
        self.status = "idle"
        self.buffer_size = 0

    def cook(self):
        """Drain points from the dtaq via repeated ``Cook(1024)`` calls.

        Tolerates up to ``exception_max`` consecutive cook failures before
        giving up.
        """
        count = 1
        exception_count = 0
        exception_max = 10
        while count > 0:
            try:
                count, points = self.dtaq.Cook(1024)
                self.acquired_points.extend(zip(*points))
            except Exception:
                LOGGER.warning("Error while cooking data from Gamry DTAQ.")
                count = 1
                exception_count += 1
                if exception_count >= exception_max:
                    LOGGER.error("Maximum number of exceptions reached while cooking data.", exc_info=True)
                    break

    def _IGamryDtaqEvents_OnDataAvailable(self):
        """COM callback invoked when new dtaq data is ready to cook."""
        self.cook()
        self.status = "measuring"

    def _IGamryDtaqEvents_OnDataDone(self):
        """COM callback invoked when the dtaq finishes; performs a final cook."""
        self.cook()  # a final cook
        self.status = "done"


@dataclass
class DummySink:
    """No-op stand-in sink used when no Gamry measurement is in progress.

    Mirrors the public attributes of ``GamryDtaqSink`` so ``GamryDriver`` can
    keep a non-None sink reference at all times.

    Attributes:
        dtaq: Always ``None``.
        status: Sink state, always ``"idle"`` on construction.
        acquired_points: Empty list of cooked points.
        buffer_size: Always 0.
    """

    dtaq: Optional[object] = None
    status: str = "idle"
    acquired_points: list = field(default_factory=list)
    buffer_size: int = 0
