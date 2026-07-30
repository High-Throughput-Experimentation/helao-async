"""Runtime introspection of a HELAO server process's loaded source files.

The hot-reload watcher needs to know which repository files a given server
process actually imported (transitively) so it can map a changed file to the
set of servers that must restart. HELAO resolves most imports dynamically (by
config string) — ``fast_launcher``/``bokeh_launcher`` ``import_module`` calls,
orchestrator ``experiment_libraries``/``sequence_libraries`` via
``import_autolibs``, config-named drivers — so a static import graph would miss
exactly the deployment code we most care about. Instead this reads the truth
that is already present in the live process: ``sys.modules``.

Only files under the repository root are reported (this includes nested
``helao/deploy/*`` deployments, which live in-tree). Each file is hashed so the
watcher can confirm an on-disk change actually differs from what the server
loaded.
"""

import hashlib
import json
import os
import sys
from typing import Optional

import helao

# Repository root = parent of the top-level ``helao`` package directory. Derived
# from the package location rather than cwd so it is correct regardless of where
# a server was launched from.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(helao.__file__)))


def _hash_file(path: str):
    """Return the SHA-1 hex digest of the file at ``path``, or None if unreadable."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return None


def loaded_repo_modules(repo_root: Optional[str] = None) -> dict:
    """Map each loaded repository ``.py`` file to its current on-disk SHA-1.

    Args:
        repo_root: Root directory to scope the scan to. Defaults to the detected
            HELAO repository root.

    Returns:
        ``{absolute_file_path: sha1_hexdigest}`` for every module in
        ``sys.modules`` whose ``__file__`` resolves under ``repo_root``. Files
        that cannot be read at query time are skipped.
    """
    root = os.path.abspath(repo_root or _REPO_ROOT)
    prefix = root + os.sep
    out = {}
    # snapshot values() first; importing during iteration would mutate sys.modules
    for mod in list(sys.modules.values()):
        f = getattr(mod, "__file__", None)
        if not f:
            continue
        af = os.path.abspath(f)
        if not af.startswith(prefix) or not af.endswith(".py"):
            continue
        digest = _hash_file(af)
        if digest is not None:
            out[af] = digest
    return out


def write_loaded_modules_snapshot(
    states_dir: str, server_key: str, repo_root: Optional[str] = None
) -> Optional[str]:
    """Persist this process's loaded-module map for the hot-reload watcher.

    Bokeh servers expose no ``/loaded_modules`` HTTP route, so the launcher's
    watcher reads a JSON snapshot at ``<states_dir>/loaded_modules_<server_key>.json``
    to map a changed repo file to the bokeh server that must restart. The
    snapshot must be (re)written whenever the set of loaded repo modules grows —
    in particular after :func:`mount_visualizers` lazily imports the per-server
    ``*_vis`` modules named by config strings, which are absent from the startup
    snapshot written before any Bokeh session connects.

    Args:
        states_dir: The server root's ``STATES`` directory.
        server_key: Config key of the bokeh server owning the snapshot.
        repo_root: Optional repo root scope forwarded to
            :func:`loaded_repo_modules`.

    Returns:
        The snapshot path on success, otherwise ``None`` (best-effort; never
        raises so a snapshot failure cannot break server bring-up).
    """
    try:
        os.makedirs(states_dir, exist_ok=True)
        snap_path = os.path.join(states_dir, f"loaded_modules_{server_key}.json")
        with open(snap_path, "w") as f:
            json.dump(loaded_repo_modules(repo_root), f)
        return snap_path
    except Exception:
        return None
