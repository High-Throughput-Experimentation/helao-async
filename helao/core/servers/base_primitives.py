"""Small dependency-free primitives shared by the ``Base`` server and its
collaborators.

Extracted from ``base.py`` (CARDS P6 follow-up) so collaborator modules can
import ``Timer`` at module top-level without forming a
``base`` <-> ``base_live_buffer`` import cycle (previously worked around with a
lazy in-method import).
"""

from time import time_ns, perf_counter_ns


class Timer:
    """Monotonic time source that returns nanoseconds aligned to the wall clock."""

    def __init__(self):
        """Capture the offset between the wall clock and the monotonic counter."""
        self._offset_ns = time_ns() - perf_counter_ns()

    def time_ns(self) -> int:
        """Return the current time in nanoseconds derived from the monotonic counter."""
        return self._offset_ns + perf_counter_ns()
