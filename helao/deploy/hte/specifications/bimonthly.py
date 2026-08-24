"""Specification parser that lists sequence zip files from the last 2 months.

Implements a :class:`BaseParser` that the orchestrator uses to surface
recently-finished sequence runs (under year/week-numbered folders) for
re-running with overridden parameters.

The window is eight weeks, not two. This module was byte-identical to
``last2weeks.py`` -- docstring, ``WEEKS = 2`` and all -- so a station
selecting "bimonthly" got a two-week lookback, and the two modules had no
reason to both exist.
"""

from helao.deploy.hte.specifications.week_window import WeekWindowSpecParser


class SpecParser(WeekWindowSpecParser):
    """Lister/parser for sequence zips collected over the last two months."""

    WEEKS = 8
