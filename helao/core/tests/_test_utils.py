"""Small helpers shared by the unit-test scripts under ``helao.core.tests``.

These tests are not pytest tests; they are scripts invoked from
``run_unit_tests.py`` that print a coloured pass/fail line per assertion
and return ``True`` only when every assertion in the script passed.

The :class:`TestReporter` class centralises the verbose try/except/print
loop used by ``unit_test_sample_models``, so individual test modules can
just write ``reporter.check("description", lambda: assertion)`` calls.
"""

__all__ = ["TestReporter"]

import sys
import traceback

import colorama
from colorama import Fore, Style


colorama.init(strip=not sys.stdout.isatty())


class TestReporter:
    """Collect and print results for a single unit-test script.

    Each call to :meth:`check` prints a numbered ``passed``/``failed`` line.
    Failures are tracked but do not abort the run, so a single script can
    surface every regression in one pass. :meth:`success` returns the
    cumulative pass flag for the caller to return from its entry point.
    """

    def __init__(self, name: str):
        """Create a fresh reporter tagged with ``name`` for the heading."""
        self.name = name
        self._counter = 1
        self._success = True
        self._fail_prefix = f"{Style.BRIGHT}{Fore.RED}failed:{Style.RESET_ALL}"
        self._passed_msg = f"{Style.BRIGHT}{Fore.GREEN}passed{Style.RESET_ALL}."

    def section(self, label: str) -> None:
        """Print a ``--- label ---`` heading inside the test output."""
        print(f" --- {label} ---")

    def check(self, description: str, fn) -> bool:
        """Run ``fn()`` as a boolean check and report its outcome.

        ``fn`` may either return a truthy/falsy value or raise. Any
        exception is treated as a failed assertion. The cumulative
        success flag for the script is updated.

        Args:
            description: Short label printed alongside the test number.
            fn: Zero-argument callable returning a truthy value when the
                assertion holds.

        Returns:
            ``True`` if the assertion held, ``False`` otherwise.
        """
        print(f"{self.name} test {self._counter} ", end="")
        self._counter += 1
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            print(self._fail_prefix, f"{description} -> raised {exc!r}")
            print(tb)
            self._success = False
            return False
        if result:
            print(self._passed_msg, description)
            return True
        print(self._fail_prefix, description)
        self._success = False
        return False

    def success(self) -> bool:
        """Return ``True`` only if every recorded check passed."""
        return self._success
