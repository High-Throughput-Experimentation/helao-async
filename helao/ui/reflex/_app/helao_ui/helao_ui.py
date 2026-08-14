"""Reflex CLI entrypoint.

Re-exports the app built from the HELAO global config. All real logic lives in
the module named below; keeping this file a resolver means the app stays
importable and testable outside the Reflex CLI.

``HELAO_REFLEX_APP_MODULE`` picks that module (P7f). It is set by
``reflex_launcher.build_env`` only for a ``reflex:`` server declaring
``deployment: hexagon``, so with the variable absent this imports exactly what
it always did and nothing else -- which is what makes "delete the config key"
a complete rollback. The variable name and the default are literals rather
than an import: a helper module imported here would join every launcher's
loaded-module map and move the bundle stamp of every *legacy* station, for a
module none of them serve. ``test_reflex_entry_resolver.py`` pins both
spellings against ``reflex_bundle``.
"""

import os
from importlib import import_module

app = import_module(
    os.environ.get("HELAO_REFLEX_APP_MODULE") or "helao.ui.reflex.app"
).app
