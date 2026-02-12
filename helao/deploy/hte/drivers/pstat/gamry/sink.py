from dataclasses import dataclass, field
from typing import Optional

from helao.helpers import helao_logging as logging  # get LOGGER from BaseAPI instance
LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

class GamryDtaqSink:
    """Event sink for reading data from Gamry device."""

    def __init__(self, dtaq):
        self.dtaq = dtaq
        self.acquired_points = []
        self.status = "idle"
        self.buffer_size = 0

    def cook(self):
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
        self.cook()
        self.status = "measuring"

    def _IGamryDtaqEvents_OnDataDone(self):
        self.cook()  # a final cook
        self.status = "done"


@dataclass
class DummySink:
    """Dummy class for when the Gamry is not used."""

    dtaq: Optional[object] = None
    status: str = "idle"
    acquired_points: list = field(default_factory=list)
    buffer_size: int = 0
