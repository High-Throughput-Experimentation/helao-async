"""Install the packages a station's servers need, from its config prefixes.

    python helao_env.py setup  <prefix|deployment/prefix|path> ...
    python helao_env.py update [<prefix> ...]

Called by setup_env/update_env after the base env exists. A prefix resolves
against every helao/deploy/*/configs/; a prefix found in several deployments is
asked about on a terminal and is an error without one. The resolved config paths
are recorded in <root>/STATES/setup_env_prefixes.json per config root, and the
conda env var HELAO_STATION_PREFIXES lists those files, so a later update with
no arguments reinstalls the same set.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DEPLOY_ROOT = REPO_ROOT / "helao" / "deploy"
ENV_VAR = "HELAO_STATION_PREFIXES"
STATES_FILE = "setup_env_prefixes.json"


class EnvSetupError(Exception):
    """A config or install step that cannot proceed; the message says why."""


def resolve_config(
    arg: str,
    deploy_root: Path = DEPLOY_ROOT,
    ask=input,
    interactive: bool | None = None,
) -> Path:
    """One config file for ``arg``: a path, ``deployment/prefix`` or a bare prefix."""
    path = Path(arg)
    if path.suffix in (".yml", ".py"):
        if path.is_file():
            return path.resolve()
        raise EnvSetupError(f"config file not found: {arg}")
    dep, _, prefix = arg.rpartition("/")
    pattern = f"{dep or '*'}/configs/{prefix}"
    matches = sorted(deploy_root.glob(f"{pattern}.yml")) or sorted(
        deploy_root.glob(f"{pattern}.py")
    )
    if not matches:
        raise EnvSetupError(f"no config named {arg!r} in any deployment")
    if len(matches) == 1:
        return matches[0].resolve()
    listing = "\n".join(
        f"  {i}. {m.relative_to(deploy_root)}" for i, m in enumerate(matches, 1)
    )
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        raise EnvSetupError(
            f"config prefix {arg!r} exists in several deployments:\n{listing}\n"
            f"pass <deployment>/{prefix} or a full path"
        )
    while True:
        answer = ask(f"{arg!r} exists in several deployments:\n{listing}\nwhich one? ")
        if answer.strip().isdigit() and 1 <= int(answer) <= len(matches):
            return matches[int(answer) - 1].resolve()


def server_folders(config_path: Path) -> set[Path]:
    """Folders holding this config's server modules (where env files live)."""
    import logging

    from helao.helpers import server_modules
    from helao.helpers.config_loader import read_config
    from helao.helpers.launcher_bootstrap import resolve_app_deployment

    cfg = read_config(str(config_path))
    log = logging.getLogger("helao_env")
    folders: set[Path] = set()
    for key, entry in (cfg.get("servers") or {}).items():
        module = entry.get("fast") or entry.get("bokeh")
        if not module:
            continue  # reflex: names a bundle, not a module
        try:
            dep = resolve_app_deployment(entry, module, str(config_path), log)
            path = server_modules.module_file(dep, module, "app")
        except (FileNotFoundError, server_modules.AmbiguousModule) as exc:
            raise EnvSetupError(f"{config_path.name}: server {key}: {exc}") from exc
        if path is None:
            raise EnvSetupError(
                f"{config_path.name}: server {key}: deployment {dep!r} has no {module!r}"
            )
        folder = path.parent
        if folder.name in ("bokeh", "reflex"):
            folder = folder.parent
        folders.add(folder)
    return folders


def _yaml():
    from ruamel.yaml import YAML

    return YAML(typ="safe")


def merge_environment(folders) -> dict | None:
    """One conda env spec from every folder's environment.yml (union, order kept)."""
    channels: list[str] = []
    deps: list[str] = []
    pip: list[str] = []
    for folder in sorted(folders):
        f = Path(folder) / "environment.yml"
        if not f.is_file():
            continue
        data = _yaml().load(f.read_text(encoding="utf-8")) or {}
        channels += [c for c in data.get("channels", []) if c not in channels]
        for d in data.get("dependencies", []):
            if isinstance(d, dict):
                pip += [p for p in d.get("pip", []) if p not in pip]
            elif d not in deps:
                deps.append(d)
    if not deps and not pip:
        return None
    return {
        "channels": channels or ["conda-forge"],
        "dependencies": deps + ([{"pip": pip}] if pip else []),
    }


def _conda() -> str:
    return os.environ.get("CONDA_EXE", "conda")


def _run(cmd: list[str]) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def install(folders, runner=_run, dry_run: bool = False) -> list[list[str]]:
    """Conda first (one merged update), then uv per folder requirements.txt."""
    cmds: list[list[str]] = []
    env = merge_environment(folders)
    if env is not None:
        tmp = Path(tempfile.mkdtemp()) / "station_env.yml"
        with open(tmp, "w", encoding="utf-8") as fh:
            _yaml().dump(env, fh)
        cmds.append(
            [
                _conda(),
                "env",
                "update",
                "--solver=rattler",
                "--prefix",
                sys.prefix,
                "-f",
                str(tmp),
            ]
        )
    for folder in sorted(folders):
        req = Path(folder) / "requirements.txt"
        if req.is_file():
            cmds.append(
                ["uv", "pip", "install", "--python", sys.executable, "-r", str(req)]
            )
    for cmd in cmds:
        (print if dry_run else runner)(cmd)
    return cmds


def _warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def _states_files(env) -> list[Path]:
    return [Path(p) for p in env.get(ENV_VAR, "").split(os.pathsep) if p]


def stored_configs(env=os.environ) -> list[Path]:
    """Config paths recorded by earlier setup runs; missing ones are skipped."""
    out: list[Path] = []
    for states in _states_files(env):
        if not states.is_file():
            _warn(f"{ENV_VAR} lists {states}, which does not exist; skipped")
            continue
        for p in json.loads(states.read_text(encoding="utf-8")):
            if Path(p).is_file():
                out.append(Path(p))
            else:
                _warn(f"recorded config {p} no longer exists; skipped")
    return out


def record(configs, runner=_run) -> list[Path]:
    """Add ``configs`` to <root>/STATES/setup_env_prefixes.json; point the env var."""
    from helao.helpers.config_loader import read_config

    files = set(_states_files(os.environ))
    written: list[Path] = []
    for cfg in configs:
        root = read_config(str(cfg)).get("root")
        if not root:
            _warn(f"{cfg} has no root:, so its prefix is not recorded")
            continue
        states = (REPO_ROOT / root).resolve() / "STATES" / STATES_FILE
        states.parent.mkdir(parents=True, exist_ok=True)
        known = (
            set(json.loads(states.read_text(encoding="utf-8")))
            if states.is_file()
            else set()
        )
        known.add(str(Path(cfg).resolve()))
        states.write_text(json.dumps(sorted(known), indent=2), encoding="utf-8")
        files.add(states)
        if states not in written:
            written.append(states)
    if written:
        runner(
            [
                _conda(),
                "env",
                "config",
                "vars",
                "set",
                "--prefix",
                sys.prefix,
                f"{ENV_VAR}={os.pathsep.join(sorted(map(str, files)))}",
            ]
        )
    return written


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="helao_env.py")
    p.add_argument("mode", choices=["setup", "update"])
    p.add_argument("prefixes", nargs="*")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    try:
        if a.prefixes:
            configs = [resolve_config(x) for x in a.prefixes]
        elif a.mode == "update":
            configs = stored_configs()
        else:
            configs = []
        if not configs:
            print(
                "no station configs given or recorded: base env only. Run "
                "setup_env <config prefix> ... to install a station's packages."
            )
            return 0
        folders: set[Path] = set()
        for cfg in configs:
            folders |= server_folders(cfg)
        install(folders, dry_run=a.dry_run)
        if a.prefixes and not a.dry_run:
            record(configs)
        for folder in sorted(folders):
            if (folder / "README.md").is_file():
                print(f"vendor notes: {folder / 'README.md'}")
        return 0
    except (EnvSetupError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
