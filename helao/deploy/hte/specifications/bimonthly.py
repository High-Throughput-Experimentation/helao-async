"""Specification parser that lists sequence zip files from the last 2 weeks.

Implements a :class:`BaseParser` that the orchestrator uses to surface
recently-finished sequence runs (under year/week-numbered folders) for
re-running with overridden parameters.
"""

from helao.deploy.hte.specifications.week_window import WeekWindowSpecParser


class SpecParser(WeekWindowSpecParser):
    """Lister/parser for sequence zips collected over the last two weeks."""

    WEEKS = 2
