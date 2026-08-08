"""Build the Reflex frontend bundle for one orchestration group.

The exported bundle is static files, but it is **not portable between
configs**: Reflex bakes the backend URL into the JavaScript at export time, and
this config's panel selection compiles in with it. A bundle built for one
config renders under another and then has every WebSocket refused -- the page
looks broken with nothing in the logs to say why. This script takes the config,
reads its Reflex server, and builds with the matching URL, installing the
result under that server's own bundle directory (see ``reflex_bundle.py``).

Usage::

    python build_reflex_bundle.py <config_prefix_or_path> [--server KEY]

The config may be a prefix (``goldenreflex``) or a path, exactly as
``launch.py`` accepts. The Reflex server is found automatically when the
config has one; ``--server`` picks between several.

Running this by hand is only needed for the *first* build on a machine, which
downloads ~270 MB of npm packages. After that ``reflex_launcher`` notices a
stale bundle and rebuilds it during launch in a few seconds, so a station's UI
follows its code without anyone remembering to run this.

Requires a JavaScript runtime (``bun`` or ``node``) on ``PATH``.
"""

__all__ = ["find_reflex_server", "staging_is_usable", "build_bundle", "main"]

import argparse
import os
import sys

from helao.helpers.config_loader import read_config
from reflex_bundle import (
    api_url_for,
    build_lock,
    install_dir,
    node_modules_present,
    staging_is_usable,
)
from reflex_bundle import build_bundle as _build_bundle


def find_reflex_server(world_cfg: dict, server_key: str = "") -> tuple:
    """Locate the config's Reflex server.

    Args:
        world_cfg: Loaded world config.
        server_key: Explicit server key, when the config has more than one.

    Returns:
        tuple: ``(server_key, host, port)``.

    Raises:
        SystemExit: When no Reflex server is present, the named one is not,
            or several exist and none was named. Each case is something the
            caller must decide, not something to guess at.
    """
    servers = world_cfg.get("servers") or {}
    reflex_servers = [
        (key, cfg)
        for key, cfg in servers.items()
        if isinstance(cfg, dict) and cfg.get("reflex")
    ]
    if not reflex_servers:
        raise SystemExit(
            "this config declares no `reflex:` server, so there is no bundle "
            "to build. Add one (it takes two consecutive ports: `port` for the "
            "frontend and `port + 1` for the backend) and try again."
        )
    if server_key:
        matched = [entry for entry in reflex_servers if entry[0] == server_key]
        if not matched:
            available = ", ".join(key for key, _ in reflex_servers)
            raise SystemExit(
                f"no Reflex server named '{server_key}' in this config; "
                f"it has: {available}"
            )
        key, cfg = matched[0]
    elif len(reflex_servers) > 1:
        available = ", ".join(key for key, _ in reflex_servers)
        raise SystemExit(
            f"this config has several Reflex servers ({available}); name one "
            "with --server. They listen on different ports, and the bundle is "
            "built for exactly one of them."
        )
    else:
        key, cfg = reflex_servers[0]
    host = cfg.get("host") or "127.0.0.1"
    port = cfg.get("port")
    if port is None:
        raise SystemExit(f"Reflex server '{key}' declares no port")
    return key, host, int(port)


def build_bundle(config_arg: str, server_key: str = "") -> str:
    """Build and install the bundle for one config, from the command line.

    The stamp recorded beside the bundle is computed **after** the Reflex app
    has been imported here, for the same reason the launcher imports it first:
    the stamp's module map is read from ``sys.modules`` and the panel modules
    arrive during that import. A stamp written without them could never
    mismatch, so the bundle would never be rebuilt again.

    Returns:
        str: The installed bundle directory.
    """
    repo_root = os.path.dirname(os.path.abspath(__file__))
    world_cfg = read_config(config_arg)
    key, host, port = find_reflex_server(world_cfg, server_key)
    api_url = api_url_for(host, port)
    root = world_cfg.get("root")
    config_prefix = os.path.splitext(os.path.basename(str(config_arg)))[0]
    print(f"config '{config_arg}': Reflex server '{key}' on {host}:{port}")
    print(f"backend URL baked into the bundle: {api_url}")
    print(f"installing to: {install_dir(repo_root, root, config_prefix, key)}")
    if not node_modules_present(repo_root):
        print(
            "no .web/node_modules yet, so this first build also downloads the "
            "npm packages (~270 MB). Later rebuilds take a few seconds and "
            "happen automatically at launch."
        )

    # The export reads the app through the `reflex` CLI in a subprocess, which
    # does not populate *this* process's sys.modules; import it here so the
    # stamp sees the panel modules.
    os.environ["HELAO_REFLEX_CONFIG"] = str(config_arg)
    os.environ["HELAO_REFLEX_SERVER_KEY"] = key
    os.environ["HELAO_REFLEX_API_URL"] = api_url
    from helao.core.servers.reflex import app as _reflex_app  # noqa: F401

    with build_lock(repo_root):
        target = _build_bundle(
            repo_root=repo_root,
            config_arg=config_arg,
            server_key=key,
            api_url=api_url,
            root=root,
            config_prefix=config_prefix,
        )
    print(f"bundle installed at {target}")
    return target


def main(argv=None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Build the Reflex frontend bundle for one config.",
    )
    parser.add_argument("config", help="config prefix or path, as launch.py accepts")
    parser.add_argument(
        "--server",
        default="",
        help="Reflex server key, when the config declares more than one",
    )
    args = parser.parse_args(argv)
    build_bundle(args.config, args.server)
    print(
        "\nThis bundle is valid only for that config and that server. Any "
        "other one gets its own; nothing needs to be rebuilt by hand when this "
        "one goes stale."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
