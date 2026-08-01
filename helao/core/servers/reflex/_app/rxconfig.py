"""Reflex project config for the HELAO UI app.

The ``reflex`` CLI requires a project directory containing ``rxconfig.py`` and
a same-named app package. ``reflex_launcher.py`` runs the CLI from this
directory; the app itself lives in ``helao.core.servers.reflex.app`` so it is
importable and testable as ordinary repository code.

Ports come from the environment because they are per-config, not per-project:
``reflex_launcher.py`` sets them from the server entry.
"""

import os

import reflex as rx

config = rx.Config(
    app_name="helao_ui",
    frontend_port=int(os.environ.get("HELAO_REFLEX_FRONTEND_PORT", "5010")),
    backend_port=int(os.environ.get("HELAO_REFLEX_BACKEND_PORT", "5011")),
    api_url=os.environ.get("HELAO_REFLEX_API_URL", "http://127.0.0.1:5011"),
)
