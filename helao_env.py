"""Install the packages a station's servers need, from its config prefixes.

    python helao_env.py setup  <prefix|deployment/prefix|path> ...
    python helao_env.py update [<prefix> ...]

Called by setup_env/update_env with the base pixi env's python. The host
workspace <repo>/.helao-env/pixi.toml is composed from the tracked base
pixi.toml plus the env files of the configs' server folders
(pixi_compose.py), its lock is seeded from the tracked pixi.lock, and
`pixi install` applies it. A prefix resolves against every
helao/deploy/*/configs/; one found in several deployments is asked about on
a terminal and is an error without one. Resolved config paths are recorded
in <root>/STATES/setup_env_prefixes.json per config root; the env var
HELAO_STATION_PREFIXES (set by the env's activation) lists those files, so a
later update with no arguments reinstalls the same set.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DEPLOY_ROOT = REPO_ROOT / "helao" / "deploy"
ENV_VAR = "HELAO_STATION_PREFIXES"
STATES_FILE = "setup_env_prefixes.json"
HTE_DIR = "hte"
#: The one place the hte deployment's remote is named (spec §3).
HTE_URL = "https://github.com/High-Throughput-Experimentation/helao-hte-deployment.git"
WORKSPACE = REPO_ROOT / ".helao-env"
BASE_MANIFEST = REPO_ROOT / "pixi.toml"
BASE_LOCK = REPO_ROOT / "pixi.lock"


class EnvSetupError(Exception):
    """A config or install step that cannot proceed; the message says why."""


class ConfigNotFound(EnvSetupError):
    """A bare prefix or deployment/prefix that no present deployment holds."""


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
    dep, _, prefix = arg.replace("\\", "/").rpartition("/")
    pattern = f"{dep or '*'}/configs/{prefix}"
    matches = sorted(deploy_root.glob(f"{pattern}.yml"))
    have = {m.parent for m in matches}  # .yml wins over .py within a deployment
    matches += sorted(
        m for m in deploy_root.glob(f"{pattern}.py") if m.parent not in have
    )
    matches.sort()
    if not matches:
        raise ConfigNotFound(f"no config named {arg!r} in any deployment")
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
        try:
            answer = ask(
                f"{arg!r} exists in several deployments:\n{listing}\nwhich one? "
            )
        except EOFError:
            raise EnvSetupError(
                f"config prefix {arg!r} exists in several deployments and no "
                "answer was given; pass <deployment>/<prefix>"
            ) from None
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
        folders.add(path.parent)
    return folders


def _yaml():
    from ruamel.yaml import YAML

    return YAML(typ="safe")


def platform_tag() -> str:
    """Conda subdir of the running interpreter (the per-platform file suffix)."""
    machine = platform.machine().lower()
    if sys.platform == "win32":
        return "win-64"
    if sys.platform == "darwin":
        return "osx-arm64" if machine in ("arm64", "aarch64") else "osx-64"
    return "linux-aarch64" if machine in ("aarch64", "arm64") else "linux-64"


def _pixi() -> str:
    """The pixi executable: $PIXI, then PATH, then ~/.pixi/bin."""
    if os.environ.get("PIXI"):
        return os.environ["PIXI"]
    found = shutil.which("pixi")
    if found:
        return found
    exe = "pixi.exe" if sys.platform == "win32" else "pixi"
    home = Path.home() / ".pixi" / "bin" / exe
    if home.is_file():
        return str(home)
    raise EnvSetupError(
        "pixi not found on PATH or in ~/.pixi/bin; run setup_env to install it"
    )


def _run(cmd: list[str]) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def pip_env_overrides(folder) -> dict[str, str]:
    """VAR: value templates from <folder>/pip_env_<platform>.yml (unexpanded).

    Empty if the file is absent, or has no requirements.txt beside it (warned).
    """
    f = Path(folder) / f"pip_env_{platform_tag()}.yml"
    if not f.is_file():
        return {}
    if not (Path(folder) / "requirements.txt").is_file():
        _warn(f"{f} has no requirements.txt beside it; ignored")
        return {}
    data = _yaml().load(f.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict) or any(
        isinstance(v, (dict, list)) for v in data.values()
    ):
        raise EnvSetupError(f"{f}: expected a flat VAR: value mapping")
    win = platform_tag().startswith("win")
    return {
        (str(k).upper() if win else str(k)): "" if v is None else str(v)
        for k, v in data.items()
    }


def _warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def _rmtree_force(path: Path) -> None:
    """rmtree that clears read-only bits (git packs on Windows); never swallows.

    Only entries inside ``path`` are chmod-ed (bits are added, never reset), a
    symlinked ``path`` is unlinked rather than followed, and every failure is an
    EnvSetupError naming the folder.
    """
    path = Path(path)
    hand = f"cannot remove {path}; delete it by hand"

    def inside(q: Path) -> bool:
        return q == path or path in q.parents

    def onexc(func, p, exc):  # noqa: ARG001
        p = Path(p)
        try:
            for q in (p.parent, p):  # unlink needs a writable parent
                if inside(q) and q.exists() and not q.is_symlink():
                    os.chmod(q, os.stat(q).st_mode | stat.S_IRWXU)
            if p.is_symlink() or p.is_file():
                os.unlink(p)
            elif p.is_dir():
                shutil.rmtree(p)
        except Exception as e:
            raise EnvSetupError(hand) from e

    if path.is_symlink():
        try:
            os.unlink(path)
        except OSError as e:
            raise EnvSetupError(hand) from e
    elif path.exists():
        shutil.rmtree(path, onexc=onexc)
    if path.is_symlink() or path.exists():
        raise EnvSetupError(hand)


def _leftover_files(root: Path) -> list[Path]:
    return [
        p
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    ]


def _git_out(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args], capture_output=True, text=True
    )


def hte_state(deploy_root: Path = DEPLOY_ROOT, repo_root: Path = REPO_ROOT) -> str:
    """What the hte folder is: its own clone, part of this checkout, leftover or absent.

    "tracked" is every checkout before the split: the folder has no .git but
    this repo tracks it, so it is the deployment, not a leftover. Anything that
    stops git from answering raises, so a folder is never called a leftover
    on a guess.
    """
    hte = Path(deploy_root) / HTE_DIR
    if hte.is_symlink() or (hte.exists() and not hte.is_dir()):
        raise EnvSetupError(f"{hte} is a symlink or not a directory; not touching it")
    if (hte / ".git").exists():
        return "repo"
    if not hte.exists():
        return "missing"
    stray = [
        k for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE") if k in os.environ
    ]
    if stray:
        raise EnvSetupError(f"{', '.join(stray)} set; cannot tell if {hte} is tracked")
    root = Path(repo_root).resolve()
    top = _git_out(root, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root:
        raise EnvSetupError(
            f"{repo_root} is not a git checkout root; not touching {hte}"
        )
    if not hte.resolve().is_relative_to(root):
        raise EnvSetupError(f"{hte} is outside {repo_root}; not touching it")
    ls = _git_out(
        root, "ls-files", "--error-unmatch", str(hte.resolve().relative_to(root))
    )
    if ls.returncode == 0:
        return "tracked"
    if ls.returncode == 1:
        return "leftover"
    raise subprocess.CalledProcessError(ls.returncode, ls.args, ls.stdout, ls.stderr)


def ensure_hte(
    deploy_root: Path = DEPLOY_ROOT,
    repo_root: Path = REPO_ROOT,
    url: str = HTE_URL,
    runner=_run,
    dry_run: bool = False,
) -> str:
    """Pull hte if it is a clone, clone it if missing, replace a leftover with a clone.

    A clone first gets its deleted tracked files restored (a parent checkout
    that still tracks hte empties it); modified and untracked files are never
    touched. A leftover is what a parent pull leaves after the split:
    __pycache__ plus any station-local files. A replacement clones first into a
    scratch folder beside the checkout (outside helao/deploy, which launchers
    glob), moves the leftover to STATES/hte_leftover_<time>/ (never deleted: it
    may hold untracked and ignored station files), logs every non-cache file in
    it to stderr and STATES/hte_leftover_<time>.txt, then swaps the clone in. Any
    failure puts the leftover back. The archive move is a plain rename, so if
    STATES is on another filesystem it fails closed and hte is left untouched.
    A stranded .hte-leftover.tmp from an older run makes this raise, which
    blocks every run that needs hte until an operator inspects it; main() warns
    and continues for runs that do not need hte.
    A failed clone or pull (non-fast-forward, local edits in the way) raises and
    leaves the existing folder as it was.
    """
    hte = Path(deploy_root) / HTE_DIR
    repo_root = Path(repo_root)
    fresh, aside = repo_root / ".hte-clone.tmp", repo_root / ".hte-leftover.tmp"
    if aside.exists():
        raise EnvSetupError(
            f"{aside} exists from an earlier run and may hold the only copy of "
            "station files; inspect it, then remove it"
        )
    state = hte_state(deploy_root, repo_root)
    if state == "tracked":
        return "tracked"
    if fresh.exists() or fresh.is_symlink():
        if dry_run:
            print(f"+ rm -r {fresh}  # stale scratch clone", flush=True)
        else:
            _warn(f"removing stale scratch clone {fresh}")
            _rmtree_force(fresh)
    if dry_run:

        def _dry_runner(cmd, env=None):  # noqa: ARG001
            print("+ " + " ".join(cmd), flush=True)

        runner = _dry_runner

    if state == "repo":
        gone = _git_out(hte, "ls-files", "-z", "--deleted")
        if gone.returncode != 0:
            raise subprocess.CalledProcessError(
                gone.returncode, gone.args, gone.stdout, gone.stderr
            )
        names = [n for n in gone.stdout.split("\0") if n]
        if names:
            print(
                f"{'would restore' if dry_run else 'restoring'} {len(names)} deleted "
                f"tracked file(s) in {hte} (a parent checkout that tracks hte empties it)",
                flush=True,
            )
            if not dry_run:
                subprocess.run(
                    [
                        "git",
                        "--literal-pathspecs",
                        "-C",
                        str(hte),
                        "checkout",
                        "--pathspec-from-file=-",
                        "--pathspec-file-nul",
                    ],
                    input="\0".join(names),
                    text=True,
                    check=True,
                )
        runner(["git", "-C", str(hte), "pull", "--ff-only"])
        return "pulled"
    if state == "missing":
        runner(["git", "clone", url, str(hte)])
        return "cloned"
    stamp = time.strftime("%Y%m%d_%H%M%S")
    states = repo_root / "STATES"
    archive = states / f"hte_leftover_{stamp}"
    if dry_run:
        runner(["git", "clone", url, str(fresh)])
        print(f"+ mv {hte} {archive}", flush=True)
        for p in _leftover_files(hte):
            _warn(f"would archive leftover {p}")
        print(f"+ mv {fresh} {hte}", flush=True)
        return "replaced"
    if archive.exists():
        raise EnvSetupError(f"{archive} already exists; run again in a second")
    try:
        runner(["git", "clone", url, str(fresh)])
    except BaseException:
        _rmtree_force(fresh)
        raise
    try:
        states.mkdir(exist_ok=True)
        hte.rename(archive)
    except BaseException:  # nothing moved: only the scratch clone to drop
        _rmtree_force(fresh)
        raise
    try:
        files = [hte / p.relative_to(archive) for p in _leftover_files(archive)]
        for p in files:
            _warn(f"archiving leftover {p}")
        (states / f"hte_leftover_{stamp}.txt").write_text(
            "".join(f"{p}\n" for p in files), encoding="utf-8"
        )
        fresh.rename(hte)
    except BaseException:
        archive.rename(hte)  # put the leftover back before anything else
        _rmtree_force(fresh)
        raise
    print(f"hte leftover archived to {archive} (file list: {archive}.txt)", flush=True)
    return "replaced"


def install(
    folders, states_files=(), runner=None, dry_run: bool = False, workspace=None
) -> dict:
    """Compose <workspace>/pixi.toml, seed its lock, run `pixi install`, and
    warn about base packages the station's additions moved."""
    import tomllib

    import tomli_w

    import pixi_compose as pc

    runner = runner or _run
    workspace = Path(workspace or WORKSPACE)
    tag = platform_tag()
    base = tomllib.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
    try:
        manifest = pc.compose(
            base,
            folders,
            tag,
            REPO_ROOT,
            states_files,
            pip_env_for=pip_env_overrides,
            warn=_warn,
        )
    except pc.ComposeError as exc:
        raise EnvSetupError(str(exc)) from exc
    text = tomli_w.dumps(manifest)
    target = workspace / "pixi.toml"
    if dry_run:
        print(f"# would write {target}:\n{text}", flush=True)
        print(f"+ pixi install --manifest-path {target}", flush=True)
        return manifest
    names = ("pixi.toml", "pixi.lock", ".seed")
    before = {
        n: (workspace / n).read_bytes() for n in names if (workspace / n).is_file()
    }
    workspace.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    key = pc.platform_key(manifest)
    try:
        if pc.seed_lock(BASE_LOCK, workspace):
            print(f"seeded {workspace / 'pixi.lock'} from {BASE_LOCK}", flush=True)
        runner([_pixi(), "install", "--manifest-path", str(target)])
    except BaseException:  # a failed install leaves the previous workspace intact
        for n in names:
            if n in before:
                (workspace / n).write_bytes(before[n])
            else:
                (workspace / n).unlink(missing_ok=True)
        raise
    for name, want, got in pc.drift(BASE_LOCK, workspace / "pixi.lock", key):
        _warn(
            f"base package {name} {want} -> {got or '(absent)'} "
            "(forced by station packages)"
        )
    return manifest


def _states_files(env) -> list[Path]:
    return [Path(p) for p in env.get(ENV_VAR, "").split(os.pathsep) if p]


def _load_states(states: Path) -> list[str]:
    try:
        return json.loads(states.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EnvSetupError(f"{states} is not valid JSON: {exc}") from exc


def stored_configs(env=os.environ) -> list[Path]:
    """Config paths recorded by earlier setup runs; missing ones are skipped."""
    out: list[Path] = []
    for states in _states_files(env):
        if not states.is_file():
            _warn(f"{ENV_VAR} lists {states}, which does not exist; skipped")
            continue
        for p in _load_states(states):
            if Path(p).is_file():
                out.append(Path(p))
            else:
                _warn(f"recorded config {p} no longer exists; skipped")
    return out


def states_paths(configs) -> list[Path]:
    """The states file of each config's root (no writes; warns on no root:)."""
    from helao.helpers.config_loader import read_config

    out: set[Path] = set()
    for cfg in configs:
        root = read_config(str(cfg)).get("root")
        if not root:
            _warn(f"{cfg} has no root:, so its prefix is not recorded")
            continue
        out.add((REPO_ROOT / root).resolve() / "STATES" / STATES_FILE)
    return sorted(out)


def _write_states(states: Path, cfg) -> None:
    states.parent.mkdir(parents=True, exist_ok=True)
    known = set(_load_states(states)) if states.is_file() else set()
    known.add(str(Path(cfg).resolve()))
    states.write_text(json.dumps(sorted(known), indent=2), encoding="utf-8")


def record(configs) -> list[Path]:
    """Add ``configs`` to <root>/STATES/setup_env_prefixes.json; return every
    states file (those already in HELAO_STATION_PREFIXES plus those written)."""
    from helao.helpers.config_loader import read_config

    files = set(_states_files(os.environ))
    for cfg in configs:
        root = read_config(str(cfg)).get("root")
        if not root:
            _warn(f"{cfg} has no root:, so its prefix is not recorded")
            continue
        states = (REPO_ROOT / root).resolve() / "STATES" / STATES_FILE
        _write_states(states, cfg)
        files.add(states)
    return sorted(files)


_PANEL_KEYS = ("action_vis", "live_vis", "control_vis")


def config_hte_use(config_path: Path, deploy_root: Path = DEPLOY_ROOT) -> str:
    """ "hte" if the config launches an hte server or panel, "unresolved" if a
    module resolves in no deployment present, else "none"."""
    from helao.helpers import server_modules
    from helao.helpers.config_loader import read_config

    path = Path(config_path).resolve()
    own = path.parents[1].name
    if own == "hte":
        return "hte"
    verdict = "none"
    for entry in (read_config(str(path)).get("servers") or {}).values():
        if not isinstance(entry, dict):
            continue
        if entry.get("deployment") == "hte":
            verdict = "hte"
        wanted = []
        if entry.get("fast") or entry.get("bokeh"):
            wanted.append((entry.get("fast") or entry.get("bokeh"), ("app",)))
        for key in _PANEL_KEYS:
            v = entry.get(key)
            for name in v if isinstance(v, list) else [v] if isinstance(v, str) else []:
                wanted.append((name, ("bokeh", "reflex")))
        for module, stacks in wanted:
            try:
                found = {
                    d
                    for s in stacks
                    for d in server_modules.locate(
                        module, s, own=own, deploy_root=deploy_root
                    )[1]
                }
            except server_modules.AmbiguousModule:
                continue  # server_folders reports it with the server key
            if not found:
                return "unresolved"
            if own not in found and "hte" in found:
                verdict = "hte"
    return verdict


def wants_hte(state: str, *, no_prefix: bool, unresolved: bool, uses_hte: bool) -> bool:
    """Spec section 3 "When it acts", with OQ-2: always pull a clone; clone an
    absent hte when no prefix is given, one is unresolved, or a config uses it."""
    if state in ("tracked", "unknown"):
        return False
    if state == "repo":
        return True
    return no_prefix or unresolved or uses_hte


def _recorded_paths_exist(env=os.environ) -> bool:
    """False when a recorded config under helao/deploy/hte is gone (the parent pull removed it)."""
    hte = (DEPLOY_ROOT / "hte").resolve()
    for states in _states_files(env):
        if states.is_file():
            for p in _load_states(states):
                if Path(p).resolve().is_relative_to(hte) and not Path(p).is_file():
                    return False
    return True


_HTE_ERRORS = (EnvSetupError, subprocess.CalledProcessError, OSError)


def main(argv=None) -> int:
    from ruamel.yaml.error import YAMLError

    p = argparse.ArgumentParser(prog="helao_env.py")
    p.add_argument("mode", choices=["setup", "update"])
    p.add_argument("prefixes", nargs="*")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    try:
        state, state_err = "unknown", None
        try:
            state = hte_state()
        except _HTE_ERRORS as exc:
            state_err = exc
            _warn(f"hte state unknown ({exc}); helao/deploy/hte left alone")
        acted = False

        def act(required: bool) -> None:
            """Pull/clone hte once. A failure aborts only when ``required``."""
            nonlocal acted
            if acted:
                return
            acted = True
            if state == "unknown":
                if required and state_err is not None:
                    raise state_err
                return
            try:
                result = ensure_hte(dry_run=a.dry_run)
            except _HTE_ERRORS as exc:
                if required:
                    raise
                _warn(f"hte not updated ({exc}); continuing without it")
                return
            print(f"hte: {'would be ' if a.dry_run else ''}{result}", flush=True)

        def stop_dry() -> int:
            print("dry run: resolving the configs needs the real hte; stopping here")
            return 0

        if a.prefixes:
            try:
                configs = [resolve_config(x) for x in a.prefixes]
            except ConfigNotFound:
                if not wants_hte(
                    state, no_prefix=False, unresolved=True, uses_hte=False
                ):
                    raise
                act(required=True)
                if a.dry_run and state != "unknown":
                    return stop_dry()
                configs = [resolve_config(x) for x in a.prefixes]
        elif a.mode == "update":
            if not _recorded_paths_exist() and wants_hte(
                state, no_prefix=False, unresolved=True, uses_hte=False
            ):
                act(required=True)
                if a.dry_run and state != "unknown":
                    return stop_dry()
            configs = stored_configs()
        else:
            configs = []
        uses = {config_hte_use(c) for c in configs}
        unresolved, hte_used = "unresolved" in uses, "hte" in uses
        no_prefix = not a.prefixes
        if (state == "unknown" and (unresolved or hte_used)) or wants_hte(
            state, no_prefix=no_prefix, unresolved=unresolved, uses_hte=hte_used
        ):
            act(required=unresolved or hte_used)
        if not configs:
            if a.mode == "setup":
                print(
                    "no config prefix given: base env only (pixi.toml). Add "
                    "config prefixes to setup_env to also install a station's "
                    "server packages."
                )
            else:
                print(
                    "no station configs given or recorded: base env only. A "
                    "host moving from conda must run setup_env <config prefix> "
                    "... once; the record is <root>/STATES/setup_env_prefixes.json, only its "
                    "HELAO_STATION_PREFIXES pointer lived in the conda env."
                )
        folders: set[Path] = set()
        for cfg in configs:
            folders |= server_folders(cfg)
        states = _states_files(os.environ)
        if a.prefixes:  # computed, not written: record() runs after install
            states = sorted(set(states) | set(states_paths(configs)))
        install(folders, states_files=states, dry_run=a.dry_run)
        if a.prefixes and not a.dry_run:
            record(configs)
        for folder in sorted(folders):
            if (folder / "README.md").is_file():
                print(f"vendor notes: {folder / 'README.md'}")
        return 0
    except (
        EnvSetupError,
        subprocess.CalledProcessError,
        OSError,
        ValueError,
        YAMLError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
