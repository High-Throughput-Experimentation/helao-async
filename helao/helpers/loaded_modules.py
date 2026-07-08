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

import os
import sys
import hashlib
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
