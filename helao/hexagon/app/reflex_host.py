"""P7f — the hexagon Reflex hosting facade (spec D9, lifted here).

``reflex:`` is the one code key with no module seam: its value is a BUNDLE
name, so a config cannot point it at a module the way ``fast:``/``bokeh:``
point at a graft. Routing is by environment variable instead
(``reflex_bundle.app_module_for``), and this module is what it names. The
``_app`` entry point imports ``app`` from here, so everything below runs in
the serving backend process, the ``reflex export`` process, and the launcher's
snapshot import alike.

Facade discipline, identical to P7e's ``makeVisApp``: **rendering is entirely
the legacy module's**. The Reflex app object here *is*
``helao.ui.reflex.app.app`` -- the same instance, not a rebuild --
so the browser gets a byte-identical page and the exported bundle is
byte-identical too. What hexagon routing adds is that the process is composed
rather than hexagon in name only: ``build_wiring`` runs, the ``ui_host`` port
is filled, and ``VIS_REQUIRED`` is enforced, so an uninstalled CONFIG, a
missing ``root:``, or a server key the config does not carry aborts the
import loudly instead of serving a half-built UI.

Two things that look like they could be done differently, and cannot:

* **The app is a process singleton.** ``build_ui_app`` returns the module's
  ``app`` rather than calling ``build_app`` again. Reflex registers state
  classes and event handlers in a process-global registry at class creation;
  a second ``rx.App`` over the same config would re-mint them, and the
  browser's handler names come from a bundle compiled against the first.
* **The wiring is attached to the module, not to the app object.** ``rx.App``
  is a Reflex model; attributes it does not declare are not necessarily
  settable, and a facade that mutates the legacy object is exactly the
  coupling D1/D2 forbid. Consumers read
  ``helao.hexagon.app.reflex_host.WIRING``.
"""

from typing import Any, Optional

from collections.abc import Callable

__all__ = ["ReflexAppUiHost", "WIRING", "app", "build_host_wiring", "server_key"]


class ReflexAppUiHost:
    """``UiHostPort`` adapter for a Reflex-hosting process.

    The mirror image of ``app/ui_host.py``'s ``BokehServerUiHost``: that one
    implements the document-server faces and defers ``build_ui_app``; this one
    implements ``build_ui_app`` and defers the document-server faces, because a
    Reflex process hosts no Bokeh documents. Both are ``UiHostPort`` instances
    (the Protocol is satisfied by method presence), so ``PortWiring.ui_host``
    takes either.
    """

    def start_document_host(
        self,
        routes: dict[str, Callable[[Any], Any]],
        host: str,
        port: int,
        allow_websocket_origin: Optional[list[str]] = None,
    ) -> object:
        from helao.hexagon.adapters.errors import HexagonDeferred

        raise HexagonDeferred(
            "ReflexAppUiHost.start_document_host: a Reflex process hosts no "
            "Bokeh documents; use BokehServerUiHost (app/ui_host.py)"
        )

    def stop(self, handle: object) -> None:
        from helao.hexagon.adapters.errors import HexagonDeferred

        raise HexagonDeferred("ReflexAppUiHost.stop: nothing was started by this host")

    def build_ui_app(self, config: dict) -> object:
        """Return the Reflex app object for ``config``.

        Args:
            config: The world config. Checked against the installed global
                config rather than used to rebuild: see the module docstring
                on why a second ``rx.App`` cannot be minted in one process.

        Returns:
            The legacy ``rx.App`` instance, opaque to every caller.

        Raises:
            ValueError: When asked for an app for a config other than the one
                this process was built from -- silently returning the wrong
                one would serve a UI pointed at another orchestration group.
        """
        from helao.helpers import config_loader

        installed = config_loader.CONFIG or {}
        if config and installed and config is not installed:
            asked = config.get("loaded_config_path")
            have = installed.get("loaded_config_path")
            if asked and have and asked != have:
                raise ValueError(
                    f"this Reflex process was built from '{have}' and cannot "
                    f"also serve '{asked}'; launch a second reflex server "
                    f"instead (one app object per process)"
                )
        return app


def _server_key(config) -> str:
    """Return the reflex server key this process serves.

    ``HELAO_REFLEX_SERVER_KEY`` is set by the launcher for the backend and by
    ``build_reflex_bundle`` for the export; the config scan is the same
    fallback ``helao.ui.reflex.app`` applies, so the facade and the
    module it wraps can never disagree about which server they are.
    """
    import os

    key = os.environ.get("HELAO_REFLEX_SERVER_KEY", "")
    if key:
        return key
    for candidate, entry in ((config or {}).get("servers") or {}).items():
        if isinstance(entry, dict) and entry.get("reflex"):
            return candidate
    return ""


def build_host_wiring(key: str):
    """Compose the port wiring for a Reflex-hosting process.

    Args:
        key: The reflex server's config key.

    Returns:
        PortWiring: with ``ui_host`` filled by :class:`ReflexAppUiHost`.

    Raises:
        UnwiredPortError: When a port ``VIS_REQUIRED`` names has no adapter.
        Anything ``build_wiring`` raises -- an uninstalled CONFIG, a missing
        ``root:``, an unknown server key -- propagates, which is the point:
        this runs at import, before a browser can reach a broken composition.
    """
    from helao.hexagon.app.factory import build_wiring
    from helao.hexagon.app.wiring import VIS_REQUIRED

    wiring = build_wiring(key)
    wiring.ui_host = ReflexAppUiHost()
    wiring.require(*VIS_REQUIRED)
    return wiring


# Importing the legacy module is what builds the app: its module-level
# `app = _build_from_global_config()` also INSTALLS the global config in a
# process that has none (the backend and the export are both children that
# load `HELAO_REFLEX_CONFIG` themselves). So this import must come before the
# wiring: `build_wiring` reads the installed config.
from helao.ui.reflex import app as _legacy  # noqa: E402
from helao.helpers import config_loader as _config_loader  # noqa: E402
from helao.helpers import helao_logging as _logging  # noqa: E402

#: The legacy app object itself -- identity, never a rebuild.
app = _legacy.app

#: The config key this process serves.
server_key = _server_key(_config_loader.CONFIG)

#: The composition. Attached to this module rather than to ``app``; see the
#: module docstring.
WIRING = build_host_wiring(server_key)

# One line, in the SERVING process. The launcher logs its own routing
# decision, but that is the parent: without this, "the backend is
# hexagon-hosted" could only ever be inferred from an environment variable
# nobody can see afterwards.
_LOGGER = _logging.make_logger(__file__) if _logging.LOGGER is None else _logging.LOGGER
_LOGGER.info(
    f"hexagon-composed Reflex UI for server '{server_key}' "
    f"(app delegated to {_legacy.__name__})"
)
