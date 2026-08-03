"""Reflex CLI entrypoint.

Re-exports the app built from the HELAO global config. All real logic lives in
``helao.core.servers.reflex.app``; keeping this file a one-liner means the app
stays importable and testable outside the Reflex CLI.
"""

from helao.core.servers.reflex.app import app  # noqa: F401
