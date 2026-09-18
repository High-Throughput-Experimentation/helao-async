"""Deployment code must not reach a host through ``.app``.

``ActionHost`` **is** the FastAPI app. ``Base`` was not -- it held a reference
to one -- so legacy deployment code reads the driver and the poller as
``base.app.driver`` / ``base.app.poller``. ``app`` is on
``test_action_host_member_coverage.DELIBERATELY_ABSENT``: the host does not
reproduce it, and every such expression raises

    AttributeError: 'ActionHost' object has no attribute 'app'

at the moment the action runs -- not at import, not at launch, not on the route
surface. The KMOTOR server carried one through B5 and the whole of the station
gate; it surfaced the first time an operator moved an axis at a station, because
KMOTOR runs at only two stations and neither had launched since.

That is the shape this guards: an attribute error reachable only from inside an
executor, on a server nothing in the suite constructs. The route checklists pass,
the module imports, the server answers -- and the first real action 500s.

Scoped two ways. ``helao/core/servers/`` is excluded because it is the legacy
engine, where ``self.base.app`` is correct until B7 deletes it. And only
**tracked** deployments are swept -- the private deployments nested under
``helao/deploy/`` are separate repositories whose checked-out branch this repo
cannot see, so a gate here would go red on one machine and green on another for
reasons no one can reproduce. That is D-B6.1: one gate per repo, living in that
repo. The tracked set is read from git rather than hardcoded, so a deployment
added later is swept without editing this file.
"""

import ast
import subprocess
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]


def _tracked_deployment_modules() -> list[Path]:
    """Every tracked ``helao/deploy/**/*.py``, private deployments excluded."""
    out = subprocess.run(
        ["git", "ls-files", "-z", "helao/deploy/*.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(REPO_ROOT / name for name in out.split("\0") if name)


def _app_attribute_sites(tree: ast.AST) -> list[int]:
    """Line numbers of every ``<anything>.app`` attribute read."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "app"
    ]


def test_no_deployment_module_reaches_a_host_through_app() -> None:
    modules = _tracked_deployment_modules()
    # A pathspec that matched nothing would make this test pass by sweeping
    # zero files, which is the failure mode of every static gate in this repo.
    assert len(modules) > 100, f"deployment sweep found only {len(modules)} files"

    findings: list[str] = []
    for path in modules:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            # A deployment this checkout cannot parse is not this test's
            # business; the import gates cover that.
            continue
        for lineno in _app_attribute_sites(tree):
            findings.append(f"{path.relative_to(REPO_ROOT)}:{lineno}")

    assert not findings, (
        "deployment code reads `.app` off a host object; ActionHost has no "
        "such attribute and this raises only once the action runs:\n  "
        + "\n  ".join(findings)
    )


if __name__ == "__main__":
    test_no_deployment_module_reaches_a_host_through_app()
    print("PASS")
