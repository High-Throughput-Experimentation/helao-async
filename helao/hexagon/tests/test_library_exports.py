"""Guard the experiment/sequence library export contract for tracked deployments.

``import_autolibs`` reads a module-level ``EXPERIMENTS``/``SEQUENCES`` list via
``tempd.get(f"{lib_type.upper()}S", [])``, so a library file whose list is
missing or misnamed publishes NOTHING and says nothing about it -- the
experiment is simply absent from the operator's dropdown. This closes that hole
at test time. See ``helao.helpers.lib_exports`` for the full rationale and the
per-file rules.

Scope is the deployments **tracked by this repository**. Private deployments are
separate git repositories nested in-tree and gitignored here, so listing this
repo's own tracked files excludes them structurally -- which is what we want
twice over: this repo must not name them, and each one opts itself in by calling
the same checker from its own test suite, so a deployment that is deliberately
out of scope simply never opts in.

Tests layer -- may import anything (boundary rule).
"""

import subprocess
from pathlib import Path

import pytest

from helao.helpers.lib_exports import check_library_exports, iter_library_files

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_ROOT = REPO_ROOT / "helao" / "deploy"


def _tracked_deployments() -> list[str]:
    """Deployment names this repo tracks library files for (so: not the private ones)."""
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "ls-files",
            "helao/deploy/*/experiments/*",
            "helao/deploy/*/sequences/*",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return sorted(
        {Path(p).parts[2] for p in proc.stdout.split() if len(Path(p).parts) > 2}
    )


TRACKED = _tracked_deployments()


@pytest.mark.skipif(not TRACKED, reason="git unavailable or no tracked library files")
@pytest.mark.parametrize("deployment", TRACKED)
def test_tracked_deployment_library_exports(deployment):
    problems = check_library_exports(DEPLOY_ROOT / deployment)
    assert not problems, "\n".join(problems)


@pytest.mark.skipif(not TRACKED, reason="git unavailable or no tracked library files")
def test_discovery_actually_finds_library_files():
    """Guard the guard: an empty sweep would make the checks above vacuous."""
    found = {d: len(list(iter_library_files(DEPLOY_ROOT / d))) for d in TRACKED}
    empty = [d for d, n in found.items() if n == 0]
    assert not empty, f"tracked deployments with no discovered library files: {empty}"
