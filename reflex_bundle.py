"""Config-specific Reflex frontend bundles, their staleness stamp, and the build.

A Reflex export is **not portable**. Reflex bakes the backend URL into the
JavaScript, and this app's panel selection compiles in too -- server keys appear
in the emitted bundle as literal comparisons and event-handler arguments. One
bundle is therefore valid for exactly one ``(config, reflex server)`` pair, and
the single repo-root ``.reflex-bundle/helao_ui`` that used to hold it could only
ever be right for one config at a time. Worse, being wrong is silent: the page
renders and then every WebSocket is refused, with nothing in any log.

So bundles live per pair under the server root::

    <root>/STATES/reflex-bundles/<config_prefix>_<server_key>/
        helao_ui/       # the extracted export
        bundle.json     # the stamp describing what it was built from

and every launch compares a freshly computed stamp against the recorded one.
Any difference means the installed bundle cannot be trusted, and the log names
the field that differed. Mtimes are never used: ``git checkout`` rewrites them
on files whose content did not change, and ``cp -p`` preserves them across a
copy that did.

The stamp's ``modules`` map is the interesting field. It comes from
``sys.modules`` (:func:`helao.helpers.loaded_modules.loaded_repo_modules`), so
it contains exactly the repository files the app actually imported -- including
the panel modules named by config strings, which no static scan and no
``git ls-files`` sweep could find. That also makes it a trap: capture it before
the app is imported and it degrades to a handful of entries that never change,
i.e. a bundle that is never stale. :func:`validate_stamp` refuses to write such
a stamp.
"""

__all__ = [
    "APP_NAME",
    "APP_DIR",
    "APP_MODULE_ENV",
    "ASSETS_DIR",
    "BUNDLE_DIRNAME",
    "BUNDLE_SUBDIR",
    "HEXAGON_APP_MODULE",
    "HEXAGON_DEPLOYMENT",
    "LEGACY_APP_MODULE",
    "app_module_for",
    "STAMP_NAME",
    "STAMP_SCHEMA",
    "COMPARED_FIELDS",
    "MIN_TRACKED_MODULES",
    "APP_MODULE_REL",
    "BUILD_LOCK_NAME",
    "BUILD_LOCK_TIMEOUT",
    "BundleChoice",
    "BundleStampError",
    "BuildLockBusy",
    "api_url_for",
    "backend_port",
    "baked_api_url",
    "build_bundle",
    "build_lock",
    "bundle_dir",
    "bundle_home",
    "compute_stamp",
    "effective_build_dir",
    "install_dir",
    "js_runtime",
    "legacy_bundle_dir",
    "node_modules_present",
    "read_stamp",
    "repo_revisions",
    "resolve_bundle",
    "stamp_mismatch",
    "stamp_path",
    "staging_app_dir",
    "staging_is_usable",
    "staging_root",
    "tool_versions",
    "usable_bundle",
    "validate_stamp",
    "write_stamp",
]

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from typing import NamedTuple, Optional

#: Must match ``app_name`` in ``helao/core/servers/reflex/_app/rxconfig.py``.
APP_NAME = "helao_ui"

#: Reflex project directory the CLI is invoked from, relative to the repo root.
APP_DIR = os.path.join("helao", "core", "servers", "reflex", "_app")

#: Reflex assets directory, served from the site root. xy's ESM client is
#: copied here before the frontend build so the bundle ships it and the browser
#: never reaches for a CDN.
ASSETS_DIR = os.path.join(APP_DIR, "assets")

#: Gitignored directory under the repo root. Holds per-(config, server) bundles
#: for a config with no ``root:``, and -- flat, at ``<repo>/.reflex-bundle/
#: helao_ui`` -- the pre-STATES bundle kept as a one-release fallback.
BUNDLE_DIRNAME = ".reflex-bundle"

#: Directory under ``<root>/STATES`` holding the per-(config, server) bundles.
BUNDLE_SUBDIR = "reflex-bundles"

#: Stamp filename, a sibling of the installed bundle directory.
STAMP_NAME = "bundle.json"

#: Bumped when the stamp's shape changes. A stamp from another schema is stale
#: by definition -- its fields cannot be compared meaningfully.
STAMP_SCHEMA = 1

#: Stamp fields whose difference makes the installed bundle stale. Everything
#: else in the stamp is recorded for diagnosis and deliberately not compared;
#: see ``js_runtime``.
COMPARED_FIELDS = (
    "schema",
    "api_url",
    "config_prefix",
    "server_key",
    "git_revs",
    "dirty_digests",
    "extra_files",
    "tool_versions",
    "modules",
)

#: Floor for a believable ``modules`` map. The real one is ~70 entries; a
#: capture taken before the app import is a handful. See :func:`validate_stamp`.
MIN_TRACKED_MODULES = 10

#: Repo-relative path that must appear in a believable ``modules`` map. Its
#: absence means the map was captured before the Reflex app was imported, which
#: is the failure that would make every later comparison pass vacuously.
APP_MODULE_REL = "helao/core/servers/reflex/app.py"

#: Marker Reflex writes into the export.
INDEX_NAME = "index.html"

#: Name ``reflex init`` must be given: it derives the app name from the current
#: directory and rejects ``_app``'s leading underscore, ignoring the valid
#: ``app_name`` already in rxconfig.py.
INIT_ARGS = ["init", "--name", APP_NAME, "--no-agents"]

#: Lockfile guarding the *build*, not the bundle directory. Concurrent builds
#: share one ``_app/.web`` tree per checkout, so that -- not the destination --
#: is what two launchers would corrupt. Gitignored.
BUILD_LOCK_NAME = ".reflex-build.lock"

#: How long to wait for another process's build. Generous, because the wait is
#: bounded by a real build: 4-5s incrementally, but minutes on the first one
#: (~270 MB of npm packages). Exceeding it is reported with the holder, never
#: by hanging the launch forever.
BUILD_LOCK_TIMEOUT = 900.0

#: Python distributions whose version changes the emitted JavaScript.
TRACKED_DISTRIBUTIONS = ("reflex", "reflex-components-radix", "xy")

#: Matches a baked ``http(s)://host:port`` inside an exported bundle.
_BAKED_URL_RE = re.compile(rb"https?://[A-Za-z0-9_.\-]+:\d{2,5}")

# --- Which app the entry module serves (P7f) ---------------------------------
#
# ``reflex:`` is a BUNDLE name (``helao_ui``, read by ``resolve_bundle`` and
# ``build_reflex_bundle.py``), never a module path, so unlike ``fast:``/
# ``bokeh:`` it carries no routing seam. Hexagon hosting is selected instead by
# the environment variable below, which ``_app/helao_ui/helao_ui.py`` reads.
# The variable is set ONLY for a server declaring ``deployment: hexagon``:
# absent, the entry module imports exactly the module it always did, so a
# legacy server's import path is unchanged and rollback is deleting one config
# key.

#: Environment variable naming the module the Reflex entry point imports its
#: ``app`` from. Duplicated as a literal in ``_app/helao_ui/helao_ui.py`` --
#: that file must not import anything to decide what to import, or every
#: legacy station's stamp would move for a module it does not use.
#: ``test_reflex_entry_resolver.py`` pins the two spellings together.
APP_MODULE_ENV = "HELAO_REFLEX_APP_MODULE"

#: What the entry module imports when the variable is absent.
LEGACY_APP_MODULE = "helao.core.servers.reflex.app"

#: What it imports for a ``deployment: hexagon`` reflex server.
HEXAGON_APP_MODULE = "helao.hexagon.app.reflex_host"

#: The ``deployment:`` value that selects hexagon hosting, pinned to
#: ``helao.hexagon.preflight.HEXAGON``.
HEXAGON_DEPLOYMENT = "hexagon"


def app_module_for(server_cfg) -> str:
    """Return the entry module that will serve one ``reflex:`` server.

    Args:
        server_cfg: The server's config block, or ``None``.

    Returns:
        str: :data:`HEXAGON_APP_MODULE` when the entry declares
        ``deployment: hexagon``, else :data:`LEGACY_APP_MODULE`.
    """
    if not isinstance(server_cfg, dict):
        return LEGACY_APP_MODULE
    if server_cfg.get("deployment") == HEXAGON_DEPLOYMENT:
        return HEXAGON_APP_MODULE
    return LEGACY_APP_MODULE


class BundleStampError(RuntimeError):
    """A stamp was refused as unbelievable rather than written."""


class BuildLockBusy(RuntimeError):
    """Another process holds the build lock and did not release it in time."""


class BundleChoice(NamedTuple):
    """What :func:`resolve_bundle` decided.

    ``path`` is ``""`` rather than ``None`` when there is nothing to serve, so
    the value handed to the static file server is always a ``str`` and the
    "did we find one" test is a plain truthiness check at every call site.

    Attributes:
        path: Directory to serve, or ``""`` when nothing is serveable.
        source: ``"config"`` for the current per-(config, server) bundle,
            ``"legacy"`` for the pre-STATES flat bundle, ``None`` for neither.
        reason: Why. Empty only for a current config bundle. For a stale one it
            names the stamp fields that differed; for the legacy fallback it
            names the backend URL that bundle was built for.
    """

    path: str
    source: Optional[str]
    reason: str


def backend_port(port: int) -> int:
    """Return the Reflex backend port for a server whose frontend is on ``port``."""
    return int(port) + 1


def api_url_for(host: str, port: int) -> str:
    """Return the backend URL baked into a bundle for ``host``/frontend ``port``.

    One definition, used both to build the child environment and to stamp the
    bundle. Two spellings of the same string would make every bundle read as
    stale, or -- worse -- a genuinely mismatched one read as current.
    """
    return f"http://{host}:{backend_port(port)}"


# --- Locations --------------------------------------------------------------


def bundle_home(repo_root: str, root=None) -> str:
    """Return the directory holding this machine's per-config bundles.

    Args:
        repo_root: HELAO repository root.
        root: The config's output root, or ``None`` when it declares none.

    Returns:
        ``<root>/STATES/reflex-bundles`` when there is a root, else a
        gitignored directory inside the repo. Nothing prunes ``STATES``, so a
        bundle stays until it is replaced -- 3.0 MB per pair.
    """
    if root:
        return os.path.join(str(root), "STATES", BUNDLE_SUBDIR)
    return os.path.join(repo_root, BUNDLE_DIRNAME)


def bundle_dir(repo_root: str, root, config_prefix: str, server_key: str) -> str:
    """Return the directory owning one ``(config, server)`` bundle and its stamp."""
    return os.path.join(bundle_home(repo_root, root), f"{config_prefix}_{server_key}")


def install_dir(repo_root: str, root, config_prefix: str, server_key: str) -> str:
    """Return where one ``(config, server)`` bundle's files are served from."""
    return os.path.join(
        bundle_dir(repo_root, root, config_prefix, server_key), APP_NAME
    )


def stamp_path(repo_root: str, root, config_prefix: str, server_key: str) -> str:
    """Return the stamp path for one ``(config, server)`` bundle."""
    return os.path.join(
        bundle_dir(repo_root, root, config_prefix, server_key), STAMP_NAME
    )


def legacy_bundle_dir(repo_root: str) -> str:
    """Return the pre-STATES flat bundle path, kept as a one-release fallback."""
    return os.path.join(repo_root, BUNDLE_DIRNAME, APP_NAME)


def usable_bundle(path) -> bool:
    """Whether ``path`` holds an export that can be served.

    A directory without ``index.html`` is treated as absent -- a half-written
    export must not be served. So is a zero-byte ``index.html``: that is an
    interrupted export or a partial copy, and serving it yields a blank browser
    page with nothing in the logs, where treating it as absent routes into the
    loud failure path.
    """
    if not path:
        return False
    index = os.path.join(path, INDEX_NAME)
    if not (os.path.isdir(path) and os.path.isfile(index)):
        return False
    return os.path.getsize(index) > 0


def baked_api_url(path) -> str:
    """Return the backend URL compiled into an exported bundle, if it can be read.

    The legacy fallback carries no stamp, so the only record of what it was
    built for is the JavaScript itself. Knowing it turns "this bundle may be
    wrong" into "this bundle is for port 5011 and you need 5013" -- the
    difference between a page that works and one that renders and then refuses
    every WebSocket.

    Returns:
        str: The most frequently baked ``http(s)://host:port``, or ``""`` when
        no bundle, no JavaScript, or no URL-shaped literal is found.
    """
    if not usable_bundle(path):
        return ""
    counts: dict = {}
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            if not (name.endswith(".js") or name == INDEX_NAME):
                continue
            try:
                with open(os.path.join(dirpath, name), "rb") as handle:
                    blob = handle.read()
            except OSError:
                continue
            for match in _BAKED_URL_RE.findall(blob):
                url = match.decode("ascii", "replace")
                counts[url] = counts.get(url, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda item: item[1])[0]


# --- Stamp ------------------------------------------------------------------


def _sha1_file(path) -> Optional[str]:
    """Return a file's SHA-1 hex digest, or ``None`` when it cannot be read."""
    try:
        with open(path, "rb") as handle:
            return hashlib.sha1(handle.read()).hexdigest()
    except OSError:
        return None


def _rel(repo_root: str, path: str) -> str:
    """Return ``path`` relative to ``repo_root``, with forward slashes.

    Relative and POSIX-shaped on purpose: a stamp keyed by absolute paths would
    read as entirely stale after the checkout moves, and one keyed by native
    separators would not survive being read on the other platform.
    """
    return os.path.relpath(path, repo_root).replace(os.sep, "/")


def _git_readers():
    """Return ``launch.py``'s repo discovery and HEAD reader.

    Imported here rather than at module scope so a Reflex server process does
    not pay for the launcher's imports, and borrowed rather than reimplemented
    so there is exactly one definition of "which repos" and "what revision" --
    the hot-reload watcher and this stamp must never disagree about either.
    """
    from launch import discover_git_repos, git_head

    return discover_git_repos, git_head


def _git_dirty_digest(repo: str) -> str:
    """Return a digest of ``repo``'s uncommitted state, or ``""`` when clean.

    A commit sha alone cannot see an edited panel module that was never
    committed -- the common case while developing one. ``--porcelain`` covers
    modified, staged, and untracked files; anything gitignored (``.web``, the
    build lock, the bundles themselves) is excluded by git, which is what keeps
    a build from invalidating its own stamp.
    """
    try:
        out = subprocess.run(
            ["git", "-C", repo, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return "unknown"
    if out.returncode != 0:
        return "unknown"
    body = out.stdout.strip()
    if not body:
        return ""
    return hashlib.sha1(body.encode("utf8", "replace")).hexdigest()


def repo_revisions(repo_root: str) -> tuple:
    """Return ``({repo: HEAD}, {repo: dirty digest})`` for every watched repo.

    Covers the parent repository and each nested ``helao/deploy/*`` deployment,
    which are separate git repositories in-tree: a panel module edited in one
    of those is exactly as much a bundle input as one edited here.
    """
    discover, head = _git_readers()
    revs: dict = {}
    dirty: dict = {}
    for repo in discover(repo_root):
        same = os.path.abspath(repo) == os.path.abspath(repo_root)
        key = "." if same else _rel(repo_root, repo)
        revs[key] = head(repo)
        dirty[key] = _git_dirty_digest(repo)
    return revs, dirty


def tool_versions() -> dict:
    """Return the versions of the distributions that shape the emitted bundle."""
    from importlib.metadata import PackageNotFoundError, version

    out = {}
    for dist in TRACKED_DISTRIBUTIONS:
        try:
            out[dist] = version(dist)
        except PackageNotFoundError:
            out[dist] = ""
    return out


def js_runtime() -> str:
    """Describe the JavaScript runtime on ``PATH``, for the record only.

    Deliberately **not** in :data:`COMPARED_FIELDS`. The emitted bundle is
    determined by the pinned toolchain under ``.web``, not by the interpreter
    that ran it, and comparing it would make a correct bundle unserveable on
    the one machine that cannot rebuild it -- a station with no runtime at all.
    """
    for name in ("bun", "node"):
        path = shutil.which(name)
        if not path:
            continue
        try:
            out = subprocess.run(
                [path, "--version"], capture_output=True, text=True, timeout=10
            )
            return f"{name} {out.stdout.strip()}" if out.returncode == 0 else name
        except Exception:
            return name
    return ""


def _xy_client_source() -> Optional[str]:
    """Return the path of xy's bundled ESM client, or ``None``.

    The stamp hashes this **source** rather than the copy at
    ``_app/assets/xy-client.js``, because the copy is made *by* the build. A
    stamp recorded before the first build would name a file that did not exist
    yet and would then mismatch the moment it did -- a rebuild on the launch
    after every fresh checkout. ``copy_client_asset`` is a verbatim
    ``shutil.copyfile``, so the two hashes are the same number.
    """
    try:
        import xy.widget

        return os.path.join(os.path.dirname(xy.widget.__file__), "static", "index.js")
    except Exception:
        return None


def _extra_file_digests(repo_root: str) -> dict:
    """Hash the build inputs that are not Python modules.

    ``rxconfig.py`` is read by the ``reflex`` CLI, never imported into this
    process, so ``sys.modules`` cannot see it; the xy client is shipped inside
    the bundle and is not Python at all.
    """
    out = {"rxconfig.py": _sha1_file(os.path.join(repo_root, APP_DIR, "rxconfig.py"))}
    source = _xy_client_source()
    out["xy-client.js"] = _sha1_file(source) if source else None
    return out


def compute_stamp(
    repo_root: str, api_url: str, config_prefix: str, server_key: str
) -> dict:
    """Describe everything the installed bundle should have been built from.

    **Call this only after the Reflex app has been imported.** The ``modules``
    map is read out of ``sys.modules``, and the panel modules are resolved by
    config string during that import; taken earlier it is a stub map that can
    never mismatch. :func:`validate_stamp` is the enforcement.

    Args:
        repo_root: HELAO repository root.
        api_url: The exact backend URL that will be baked into the bundle.
        config_prefix: Config prefix this bundle belongs to.
        server_key: Reflex server key this bundle belongs to.

    Returns:
        dict: A JSON-serializable stamp.
    """
    from helao.helpers.loaded_modules import loaded_repo_modules

    revs, dirty = repo_revisions(repo_root)
    # Scoped to the ``helao`` package, not the whole checkout. The repo root
    # also holds the entry-point scripts, and which of those is loaded depends
    # only on *who* is asking: a build run by `build_reflex_bundle.py` and one
    # run by `reflex_launcher.py` would otherwise differ by exactly that one
    # entry and rebuild each other's bundle forever. Nothing at the repo root
    # is importable by the Reflex app, so none of it can reach the emitted
    # JavaScript. Measured: with this scope the two processes produce identical
    # 59-entry maps; without it they differ by one entry and agree on the rest.
    modules = {
        _rel(repo_root, path): digest
        for path, digest in loaded_repo_modules(
            os.path.join(repo_root, "helao")
        ).items()
    }
    return {
        "schema": STAMP_SCHEMA,
        "api_url": api_url,
        "config_prefix": config_prefix,
        "server_key": server_key,
        "git_revs": revs,
        "dirty_digests": dirty,
        "extra_files": _extra_file_digests(repo_root),
        "tool_versions": tool_versions(),
        "modules": modules,
        # Recorded, never compared.
        "js_runtime": js_runtime(),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "built_by_host": socket.gethostname(),
    }


def validate_stamp(stamp: dict) -> None:
    """Refuse a stamp that could never mismatch.

    The ``modules`` map is the only field that notices an edited panel module
    on a station whose repo is committed and clean. If it is empty or stub-sized
    the staleness check silently degrades to "never stale" and a wrong bundle is
    served forever, with every other signal reading healthy. Failing the write
    loudly is the whole point.

    Raises:
        BundleStampError: When the map is missing, too small, or does not
            contain the Reflex app module itself.
    """
    modules = stamp.get("modules")
    if not isinstance(modules, dict):
        raise BundleStampError("stamp has no modules map")
    if APP_MODULE_REL not in modules:
        raise BundleStampError(
            f"stamp's modules map does not contain {APP_MODULE_REL}, so it was "
            "captured before the Reflex app was imported. A stamp taken then "
            "can never mismatch, and the bundle would never be rebuilt."
        )
    if len(modules) < MIN_TRACKED_MODULES:
        raise BundleStampError(
            f"stamp's modules map has only {len(modules)} entries (expected at "
            f"least {MIN_TRACKED_MODULES}); it cannot be a real capture."
        )


def write_stamp(path: str, stamp: dict) -> None:
    """Validate and persist a stamp beside its bundle.

    Raises:
        BundleStampError: Via :func:`validate_stamp`.
    """
    validate_stamp(stamp)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf8") as handle:
        json.dump(stamp, handle, indent=1, sort_keys=True)
    os.replace(tmp, path)


def read_stamp(path: str):
    """Return the recorded stamp, or ``None`` when there is none to read.

    An unreadable or malformed stamp reads as absent, which makes the bundle
    stale rather than trusted -- the safe direction.
    """
    try:
        with open(path, encoding="utf8") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _describe_map(current, recorded) -> str:
    """Name up to three keys whose values differ between two dict fields."""
    current = current if isinstance(current, dict) else {}
    recorded = recorded if isinstance(recorded, dict) else {}
    changed = [
        k
        for k in sorted(set(current) | set(recorded))
        if current.get(k) != recorded.get(k)
    ]
    shown = ", ".join(changed[:3])
    if len(changed) > 3:
        shown += f", +{len(changed) - 3} more"
    return f"{len(changed)} changed ({shown})"


def stamp_mismatch(current: dict, recorded) -> str:
    """Return why the installed bundle is stale, or ``""`` when it is current.

    Every compared field is reported, not just the first, because "the port
    changed" and "a panel module changed" call for different reactions and a
    launch that reports only one of them sends the reader down the wrong path.
    """
    if not recorded:
        return "no bundle stamp recorded"
    reasons = []
    for field in COMPARED_FIELDS:
        cur = current.get(field)
        rec = recorded.get(field)
        if cur == rec:
            continue
        if isinstance(cur, dict) or isinstance(rec, dict):
            reasons.append(f"{field} ({_describe_map(cur, rec)})")
        else:
            reasons.append(f"{field} (built for {rec!r}, need {cur!r})")
    return "; ".join(reasons)


def resolve_bundle(
    repo_root: str, root=None, config_prefix: str = "", server_key: str = "", stamp=None
) -> BundleChoice:
    """Decide what, if anything, may be served for one ``(config, server)`` pair.

    Args:
        repo_root: HELAO repository root.
        root: The config's output root, or ``None``.
        config_prefix: Config prefix.
        server_key: Reflex server key.
        stamp: The freshly computed stamp to compare against the recorded one.
            ``None`` skips the comparison, which is only correct for a caller
            that is asking about presence alone.

    Returns:
        BundleChoice: See its docstring. The legacy fallback is offered only
        when the per-config bundle is *absent* -- never when one exists and is
        stale, because then the bundle that is known to be wrong is the one
        that would be found first, and the legacy one is no more likely to be
        right.
    """
    installed = install_dir(repo_root, root, config_prefix, server_key)
    if usable_bundle(installed):
        if stamp is None:
            return BundleChoice(installed, "config", "")
        reason = stamp_mismatch(
            stamp, read_stamp(stamp_path(repo_root, root, config_prefix, server_key))
        )
        if not reason:
            return BundleChoice(installed, "config", "")
        return BundleChoice("", None, f"stale: {reason}")

    legacy = legacy_bundle_dir(repo_root)
    if usable_bundle(legacy):
        return BundleChoice(legacy, "legacy", baked_api_url(legacy))
    return BundleChoice("", None, "no bundle installed")


# --- Building ---------------------------------------------------------------


def staging_root() -> str:
    """Return the persistent, executable directory staged builds live in.

    Only used when the repository itself cannot execute (see
    :func:`staging_is_usable`). Persistent on purpose: a staged copy that was
    thrown away after each build discarded ``.web`` with it, so *every* build
    on a ``noexec`` checkout re-fetched ~270 MB and the incremental branch of
    the auto-build policy could never be reached there.

    ``HELAO_REFLEX_BUILD_DIR`` overrides it.
    """
    override = os.environ.get("HELAO_REFLEX_BUILD_DIR")
    if override:
        return override
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
            os.path.expanduser("~"), ".cache"
        )
    return os.path.join(base, "helao", "reflex-build")


def staging_app_dir(repo_root: str) -> str:
    """Return the staged ``_app`` tree for one checkout.

    Keyed by the checkout so two of them (a station and a worktree, say) never
    share one ``.web`` -- which is also what the build lock assumes.
    """
    key = hashlib.sha1(os.path.abspath(repo_root).encode("utf8")).hexdigest()[:12]
    return os.path.join(staging_root(), key, "_app")


def effective_build_dir(repo_root: str) -> str:
    """Return the directory an export would actually run from."""
    source_app = os.path.join(repo_root, APP_DIR)
    if staging_is_usable(source_app):
        return source_app
    return staging_app_dir(repo_root)


def node_modules_present(repo_root: str) -> bool:
    """Whether a build here would be incremental rather than a fresh npm fetch.

    The distinction is the whole auto-build policy: with ``.web/node_modules``
    already populated an export takes 4-5 seconds and may as well happen during
    launch, and without it the same command downloads ~270 MB, which must never
    happen unasked on an instrument PC.

    Asked of the directory the build will *run* in, not of the repository. On a
    ``noexec`` checkout those differ, and the repository's own ``.web`` is not
    the one that would be reused.
    """
    return os.path.isdir(
        os.path.join(effective_build_dir(repo_root), ".web", "node_modules")
    )


try:  # declared in the environment files; the fallback is for a stripped install
    from filelock import FileLock as _FileLock
    from filelock import Timeout as _FileLockTimeout

    _LOCK_TIMEOUTS: tuple = (TimeoutError, _FileLockTimeout)
except ImportError:  # pragma: no cover - filelock is a declared dependency
    _FileLock = None
    _LOCK_TIMEOUTS = (TimeoutError,)


class _SpinLock:
    """``O_CREAT|O_EXCL`` lockfile used when ``filelock`` is unavailable."""

    def __init__(self, lock_path: str, timeout: float):
        self.lock_path = lock_path
        self.timeout = timeout
        self._fd = None

    def acquire(self):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise TimeoutError(self.lock_path)
                time.sleep(0.1)

    def release(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            os.remove(self.lock_path)
        except OSError:
            pass


def _owner_path(lock_path: str) -> str:
    return lock_path + ".owner"


def _record_owner(lock_path: str) -> None:
    """Note who holds the lock, so a timeout can name them rather than a path."""
    try:
        with open(_owner_path(lock_path), "w", encoding="utf8") as handle:
            json.dump(
                {
                    "pid": os.getpid(),
                    "host": socket.gethostname(),
                    "since": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                },
                handle,
            )
    except OSError:
        pass


def _read_owner(lock_path: str) -> str:
    """Describe the lock's holder for an error message."""
    try:
        with open(_owner_path(lock_path), encoding="utf8") as handle:
            owner = json.load(handle)
        return (
            f"pid {owner.get('pid')} on {owner.get('host')} since "
            f"{owner.get('since')}"
        )
    except (OSError, ValueError, AttributeError):
        return "unknown holder"


class build_lock:
    """Serialize frontend builds that share one ``_app/.web`` tree.

    The lock guards the *build*, not the destination: two configs building
    concurrently write to different bundle directories but through the same
    ``.web`` working tree, which is what would be corrupted. A timeout names
    the holder and raises rather than hanging a launch indefinitely.

    Args:
        repo_root: HELAO repository root.
        timeout: Seconds to wait for another build.
        logger: Optional logger; the wait and the timeout are worth a line.
    """

    def __init__(
        self, repo_root: str, timeout: float = BUILD_LOCK_TIMEOUT, logger=None
    ):
        self.path = os.path.join(repo_root, APP_DIR, BUILD_LOCK_NAME)
        self.timeout = timeout
        self.logger = logger
        self._lock = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = (
            _FileLock(self.path, timeout=self.timeout)
            if _FileLock is not None
            else _SpinLock(self.path, self.timeout)
        )
        try:
            self._lock.acquire()
        except _LOCK_TIMEOUTS:
            holder = _read_owner(self.path)
            message = (
                f"another Reflex frontend build holds {self.path} ({holder}) and "
                f"did not finish within {self.timeout:.0f}s"
            )
            if self.logger is not None:
                self.logger.error(message)
            raise BuildLockBusy(message)
        _record_owner(self.path)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            os.remove(_owner_path(self.path))
        except OSError:
            pass
        if self._lock is not None:
            self._lock.release()
        return False


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


#: Never copied into a staged build tree: ``.web`` is the thing being kept,
#: and the rest are per-run artifacts.
_STAGE_IGNORE = (".web", ".states", "__pycache__", "frontend.zip", BUILD_LOCK_NAME)


def _sync_app_sources(source_app: str, build_dir: str) -> None:
    """Refresh a staged ``_app`` from the repository, preserving its ``.web``.

    The staged sources are *replaced*, not merged: a panel module deleted in
    the repository must disappear from the build too, and a merge would leave
    it compiled into every later bundle.
    """
    os.makedirs(build_dir, exist_ok=True)
    for name in os.listdir(build_dir):
        if name in _STAGE_IGNORE or name.startswith(BUILD_LOCK_NAME):
            continue
        path = os.path.join(build_dir, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.remove(path)
    shutil.copytree(
        source_app,
        build_dir,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*_STAGE_IGNORE, "*.pyc"),
    )


def _copy_client_asset(dest_dir: str) -> str:
    """Put xy's ESM client in a build tree's assets directory.

    A one-line indirection over ``xy_component.copy_client_asset`` so the import
    stays lazy -- it pulls in reflex and xy -- and so a test can drive the whole
    install path without either.
    """
    from helao.core.servers.reflex.xy_component import copy_client_asset

    return copy_client_asset(dest_dir)


def _run(command: list, cwd: str, env: dict, what: str, logger=None) -> None:
    """Run one build step, failing with its output rather than a bare code."""
    if logger is not None:
        logger.info(f"  {what}...")
    else:
        print(f"  {what}...", flush=True)
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-20:]
        raise SystemExit(
            f"{what} failed (exit {result.returncode}):\n" + "\n".join(tail)
        )


def build_bundle(
    repo_root: str,
    config_arg: str,
    server_key: str,
    api_url: str,
    root=None,
    config_prefix: str = "",
    stamp=None,
    logger=None,
    app_module: str = LEGACY_APP_MODULE,
) -> str:
    """Build and install the bundle for one ``(config, server)`` pair.

    The install is verify-then-replace and then a rename: the export is checked
    for a non-empty ``frontend.zip`` and an extracted ``index.html`` *before*
    anything installed is touched, then moved into place. An export can fail
    while still exiting zero, and removing a working bundle first would leave
    the station with nothing to serve.

    Args:
        repo_root: HELAO repository root.
        config_arg: Config path/prefix, forwarded to the export's environment.
        server_key: Reflex server key.
        api_url: Backend URL to bake in.
        root: The config's output root, or ``None``.
        config_prefix: Config prefix; defaults to ``config_arg``'s basename.
        stamp: Stamp to record. When ``None`` it is computed here, *after* the
            build, so the xy client asset the build itself writes is included.
        logger: Optional logger; progress goes to ``print`` without one.
        app_module: Entry module the ``reflex export`` subprocess should serve
            (:func:`app_module_for`). The export compiles whatever ``app``
            object that module exposes, so a bundle built under one routing and
            served under another would be a silent mismatch of exactly the kind
            the stamp exists to prevent -- the caller that decides the routing
            for the *backend* must decide it here too.

    Returns:
        str: The installed bundle directory.

    Raises:
        SystemExit: With the failing step's output, on any build failure.
        BundleStampError: When the stamp to record is not believable.
    """
    if not (shutil.which("bun") or shutil.which("node")):
        raise SystemExit(
            "no JavaScript runtime on PATH. The frontend build needs `bun` or "
            "`node`; install one into the helao environment "
            "(`conda install -n helao bun`) and try again."
        )
    config_prefix = config_prefix or os.path.splitext(os.path.basename(config_arg))[0]
    source_app = os.path.join(repo_root, APP_DIR)
    if not os.path.isdir(source_app):
        raise SystemExit(f"no Reflex app directory at {source_app}")

    env = dict(os.environ)
    env["HELAO_REFLEX_CONFIG"] = str(config_arg)
    env["HELAO_REFLEX_SERVER_KEY"] = server_key
    env["HELAO_REFLEX_API_URL"] = api_url
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
    # Set only under hexagon routing, and *popped* otherwise: this process may
    # have inherited the variable from a caller, and an export that silently
    # compiled a different app than the one asked for is the failure the whole
    # seam is built to avoid.
    if app_module != LEGACY_APP_MODULE:
        env[APP_MODULE_ENV] = app_module
    else:
        env.pop(APP_MODULE_ENV, None)

    target = install_dir(repo_root, root, config_prefix, server_key)
    with tempfile.TemporaryDirectory(prefix="helao-reflex-unpack-") as scratch:
        # Build in place when the repo allows it, and in a persistent staged
        # copy when it does not. Only the *build* needs an executable
        # filesystem; the bundle is static files and is served from wherever it
        # lands.
        build_dir = effective_build_dir(repo_root)
        if build_dir != source_app:
            os.makedirs(build_dir, exist_ok=True)
            if not staging_is_usable(build_dir):
                raise SystemExit(
                    f"the repository at '{repo_root}' cannot execute the npm "
                    f"binaries a frontend build runs, and neither can the "
                    f"staging directory '{build_dir}'. Point "
                    f"HELAO_REFLEX_BUILD_DIR at a filesystem mounted without "
                    f"`noexec`."
                )
            _sync_app_sources(source_app, build_dir)

        # Ship xy's ESM client inside the bundle so the browser never reaches
        # for a CDN -- a station has no internet.
        _copy_client_asset(os.path.join(build_dir, os.path.basename(ASSETS_DIR)))

        zip_path = os.path.join(build_dir, "frontend.zip")
        if os.path.exists(zip_path):
            os.remove(zip_path)
        # `python -m reflex`, not a bare `reflex`: the CLI is only on PATH
        # inside an activated environment, and this must work when the script
        # is invoked by absolute interpreter path too.
        reflex_cli = [sys.executable, "-m", "reflex"]
        if not os.path.isdir(os.path.join(build_dir, ".web")):
            _run([*reflex_cli, *INIT_ARGS], build_dir, env, "reflex init", logger)
        _run(
            [*reflex_cli, "export", "--frontend-only"],
            build_dir,
            env,
            "reflex export",
            logger,
        )

        if not (os.path.isfile(zip_path) and os.path.getsize(zip_path) > 0):
            raise SystemExit(
                "the export produced no frontend.zip; the previous bundle has "
                "been left in place"
            )
        staged = os.path.join(scratch, "unpacked")
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(staged)
        if not os.path.isfile(os.path.join(staged, INDEX_NAME)):
            raise SystemExit(
                f"the export contains no {INDEX_NAME}; the previous bundle has "
                "been left in place"
            )

        # The stamp is validated before the old bundle is disturbed, so an
        # unbelievable one fails with the working bundle still in place.
        recorded = (
            stamp
            if stamp is not None
            else compute_stamp(repo_root, api_url, config_prefix, server_key)
        )
        validate_stamp(recorded)

        os.makedirs(os.path.dirname(target), exist_ok=True)
        replaced = target + ".replacing"
        if os.path.isdir(replaced):
            shutil.rmtree(replaced)
        if os.path.isdir(target):
            os.rename(target, replaced)
        try:
            shutil.move(staged, target)
        except Exception:
            if os.path.isdir(replaced) and not os.path.isdir(target):
                os.rename(replaced, target)
            raise
        if os.path.isdir(replaced):
            shutil.rmtree(replaced, ignore_errors=True)
        write_stamp(stamp_path(repo_root, root, config_prefix, server_key), recorded)
    return target
