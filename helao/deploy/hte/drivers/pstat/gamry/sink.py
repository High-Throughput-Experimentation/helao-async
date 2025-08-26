from dataclasses import dataclass, field
from typing import Optional

class GamryDtaqSink:
    """Event sink for reading data from Gamry device."""
    def __init__(self, dtaq):
        self.dtaq = dtaq
        self.acquired_points = []
        self.status = "idle"
        self.buffer_size = 0

    def cook(self):
        count = 1
        while count > 0:
            try:
                count, points = self.dtaq.Cook(1000)
                self.acquired_points.extend(zip(*points))
            except Exception:
                count = 0

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