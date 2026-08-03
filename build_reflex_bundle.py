"""Build the Reflex frontend bundle for one orchestration group, locally.

The exported bundle is static files, but it is **not portable between
configs**: Reflex bakes the backend URL into the JavaScript at export time. A
bundle built for one config's port renders under another and then has every
WebSocket refused -- the page looks broken with nothing in the logs to say
why. This script takes the config, reads its Reflex server's port, and builds
with the matching URL, which is the whole reason it exists.

Usage::

    python build_reflex_bundle.py <config_prefix_or_path> [--server KEY]

The config may be a prefix (``goldenreflex``) or a path, exactly as
``launch.py`` accepts. The Reflex server is found automatically when the
config has one; ``--server`` picks between several.

Requires a JavaScript runtime (``bun`` or ``node``) on ``PATH``; ``nodejs`` is
in the conda environment files for that reason. Nothing else about a station
changes -- ``reflex_launcher`` still refuses to build at launch time unless
``REFLEX_ALLOW_LOCAL_BUILD=1`` is set, so a missing bundle stays a loud
failure rather than a silent multi-minute build while an operator waits.
"""

__all__ = ["find_reflex_server", "staging_is_usable", "build_bundle", "main"]

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

from helao.helpers.config_loader import read_config
from reflex_launcher import (
    APP_DIR,
    APP_NAME,
    ASSETS_DIR,
    BUNDLE_DIRNAME,
    backend_port,
)

#: Marker Reflex writes into the export.
INDEX_NAME = "index.html"

#: Name `reflex init` must be given: it derives the app name from the current
#: directory and rejects `_app`'s leading underscore, ignoring the valid
#: `app_name` already in rxconfig.py.
INIT_ARGS = ["init", "--name", APP_NAME, "--no-agents"]


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


def staging_is_usable(path: str) -> bool:
    """Whether a frontend build can run from ``path``.

    npm's binaries live under ``.web/node_modules/.bin`` and are executed
    directly, so a ``noexec`` mount fails the build with ``Permission denied``
    no matter what the permission bits say. Checked by actually running a file
    rather than reading mount flags, which vary by platform.
    """
    probe = os.path.join(path, ".helao_exec_probe")
    try:
        with open(probe, "w", encoding="utf8") as handle:
            handle.write("#!/bin/sh\nexit 0\n")
        os.chmod(probe, 0o755)
        if os.name == "nt":
            return True
        return subprocess.run([probe], capture_output=True).returncode == 0
    except Exception:
        return False
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass


def _run(command: list, cwd: str, env: dict, what: str) -> None:
    """Run one build step, failing with its output rather than a bare code."""
    print(f"  {what}...", flush=True)
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-20:]
        raise SystemExit(
            f"{what} failed (exit {result.returncode}):\n" + "\n".join(tail)
        )


def build_bundle(config_arg: str, server_key: str = "") -> str:
    """Build and install the bundle for one config.

    Returns:
        str: The installed bundle directory.
    """
    if not (shutil.which("bun") or shutil.which("node")):
        raise SystemExit(
            "no JavaScript runtime on PATH. The frontend build needs `bun` or "
            "`node`; install nodejs into the helao environment "
            "(`conda install -n helao nodejs`) and try again."
        )

    repo_root = os.path.dirname(os.path.abspath(__file__))
    world_cfg = read_config(config_arg)
    key, host, port = find_reflex_server(world_cfg, server_key)
    api_url = f"http://{host}:{backend_port(port)}"
    print(f"config '{config_arg}': Reflex server '{key}' on {host}:{port}")
    print(f"backend URL baked into the bundle: {api_url}")

    source_app = os.path.join(repo_root, APP_DIR)
    if not os.path.isdir(source_app):
        raise SystemExit(f"no Reflex app directory at {source_app}")

    env = dict(os.environ)
    env["HELAO_REFLEX_CONFIG"] = config_arg
    env["HELAO_REFLEX_SERVER_KEY"] = key
    env["HELAO_REFLEX_API_URL"] = api_url
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")

    with tempfile.TemporaryDirectory(prefix="helao-reflex-build-") as scratch:
        # Build in place when the repo allows it, and out of tree when it does
        # not. Only the *build* needs an executable filesystem; the bundle is
        # static files and is served from wherever it lands.
        if staging_is_usable(source_app):
            build_dir = source_app
            print("building in place")
        else:
            build_dir = os.path.join(scratch, "_app")
            shutil.copytree(
                source_app,
                build_dir,
                ignore=shutil.ignore_patterns(
                    ".web", ".states", "__pycache__", "*.pyc"
                ),
            )
            print(f"repo is not executable; staging the build in {build_dir}")

        from helao.core.servers.reflex.xy_component import copy_client_asset

        # Ship xy's ESM client inside the bundle so the browser never reaches
        # for a CDN -- a station has no internet.
        copy_client_asset(os.path.join(build_dir, os.path.basename(ASSETS_DIR)))

        zip_path = os.path.join(build_dir, "frontend.zip")
        if os.path.exists(zip_path):
            os.remove(zip_path)
        # `python -m reflex`, not a bare `reflex`: the CLI is only on PATH
        # inside an activated environment, and this must work when the script
        # is invoked by absolute interpreter path too.
        reflex_cli = [sys.executable, "-m", "reflex"]
        if not os.path.isdir(os.path.join(build_dir, ".web")):
            _run([*reflex_cli, *INIT_ARGS], build_dir, env, "reflex init")
        _run(
            [*reflex_cli, "export", "--frontend-only"],
            build_dir,
            env,
            "reflex export",
        )

        # Verified before the old bundle is touched. An export can fail while
        # still exiting zero, and removing a working bundle first leaves the
        # station with nothing to serve.
        if not (os.path.isfile(zip_path) and os.path.getsize(zip_path) > 0):
            raise SystemExit(
                "the export produced no frontend.zip; the previous bundle has "
                "been left in place"
            )

        target = os.path.join(repo_root, BUNDLE_DIRNAME, APP_NAME)
        staged = os.path.join(scratch, "unpacked")
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(staged)
        if not os.path.isfile(os.path.join(staged, INDEX_NAME)):
            raise SystemExit(
                f"the export contains no {INDEX_NAME}; the previous bundle has "
                "been left in place"
            )
        if os.path.isdir(target):
            shutil.rmtree(target)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.move(staged, target)

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
        "\nThis bundle is valid only for that config's port. Rebuild it if the "
        "Reflex server's port changes."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
