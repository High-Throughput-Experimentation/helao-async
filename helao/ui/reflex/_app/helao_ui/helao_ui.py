"""Reflex CLI entrypoint.

Re-exports the app built from the HELAO global config. All real logic lives in
``helao.ui.reflex.app``; this file is a thin re-export so the app stays
importable and testable outside the Reflex CLI.
"""

from helao.ui.reflex.app import app  # noqa: F401
