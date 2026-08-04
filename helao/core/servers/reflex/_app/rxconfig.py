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

# No frontend_port: reflex never serves our frontend -- reflex_launcher serves
# the exported bundle itself with uvicorn + StaticFiles so stations need no
# Node. Setting it makes `reflex run --backend-only` abort immediately with
# "Cannot specify --frontend-port when not running frontend", which is how the
# backend came to be silently absent while the UI showed only a websocket error.
config = rx.Config(
    app_name="helao_ui",
    backend_port=int(os.environ.get("HELAO_REFLEX_BACKEND_PORT", "5011")),
    api_url=os.environ.get("HELAO_REFLEX_API_URL", "http://127.0.0.1:5011"),
    plugins=[rx.plugins.TailwindV4Plugin()],
)
