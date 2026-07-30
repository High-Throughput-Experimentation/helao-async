"""Run the pytest suite one file at a time, across this repo and every deployment.

    python run_tests.py                     # everything
    python run_tests.py --filter sync       # only paths containing "sync"
    python run_tests.py --list              # show what would run, run nothing
    python run_tests.py --timeout 300       # raise the per-file cap

This is the development suite. It is deliberately NOT ``run_unit_tests.py``,
which stays a fast pre-launch gate that ``launch.py`` runs before starting a
server group -- a slow full sweep there would tax every launch, and a failure in
an unrelated deployment's tests should not block bringing a station up.

**One file per pytest process, with a hard timeout.** This is the whole point of
the script rather than a bare ``pytest``. Collecting the tree as a single
session hangs indefinitely (and swallows SIGINT), while the same files pass
individually: these tests start event loops, bind sockets, and spawn Bokeh
servers, so cross-file interference is expected rather than surprising. A
per-file cap also means one wedged file costs its timeout instead of the run.

**Deployment discovery** keys on a deployment having a ``tests/`` directory,
then sweeps that whole deployment for ``test_*.py`` -- which picks up the test
files living next to their subject (a driver test beside its driver) rather than
only those filed under ``tests/``. Deployments without a ``tests/`` dir opt out
by construction, which is also how this repo avoids naming the private
deployments nested in-tree: discovery is structural, not a hardcoded list.

Matching is on the FILE name, never the path, so a directory that merely begins
with ``test_`` (a *test station* driver package, say) does not drag its whole
contents in as if they were tests.

Third-party import failures are reported as ENV, not FAIL: a module needing a
Windows-only vendor SDK cannot be collected on Linux, and that is a property of
the machine rather than a defect. A missing *first-party* (``helao*``) module
stays a FAIL, since that is a real breakage. Files with no pytest tests -- the
standalone ``__main__`` scripts this project also calls tests -- report NOTESTS.
"""

import argparse
import ast
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

#: Test roots owned by this repo. Deployment roots are discovered, not listed.
CORE_TEST_DIRS = ("helao/hexagon/tests", "harness/tests", "helao/core/tests")

#: Never traverse these, wherever they appear.
SKIP_PARTS = {"notes", "__pycache__", ".git", ".claude", "node_modules"}

MISSING_MODULE = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")
MISSING_FIXTURE = re.compile(r"fixture '([^']+)' not found")
COUNTS = re.compile(r"(\d+) (passed|failed|error|errors|skipped|xfailed|xpassed)")


def _skipped(path: Path) -> bool:
    return any(part in SKIP_PARTS for part in path.parts)


def has_pytest_tests(path: Path) -> bool:
    """Whether ``path`` defines anything pytest would collect, decided by AST.

    Checked WITHOUT importing, which is the point. pytest imports a module while
    collecting it, so module-level code runs even when zero tests are found --
    and this tree contains ``test_*.py`` files that are manual smoke scripts,
    including one that reads ``sys.argv[1]`` as a config path and **emits a real
    email alert at import**. Sweeping those by name would fire them as a side
    effect of running the suite. Deciding from the syntax tree keeps them
    unimported, and they are reported as NOTESTS rather than silently dropped.

    Counts module-level ``def``/``async def`` named ``test_*`` and ``test_*``
    methods inside a ``Test*`` class, which is what pytest's default collection
    looks for.
    """
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError, OSError):
        return True  # let pytest report it rather than hiding it here
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                return True
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if sub.name.startswith("test"):
                        return True
    return False


def discover_deployments() -> list[Path]:
    """Deployment dirs that opt in to the suite by having a ``tests/`` directory."""
    deploy_root = REPO_ROOT / "helao" / "deploy"
    if not deploy_root.is_dir():
        return []
    return sorted(
        d
        for d in deploy_root.iterdir()
        if d.is_dir() and not _skipped(d) and (d / "tests").is_dir()
    )


def discover_files() -> list[tuple[str, Path]]:
    """``(group, path)`` for every test file to run, deduplicated, stably ordered."""
    found: dict[Path, str] = {}

    for rel in CORE_TEST_DIRS:
        base = REPO_ROOT / rel
        if base.is_dir():
            for path in sorted(base.rglob("test_*.py")):
                if not _skipped(path):
                    found.setdefault(path, rel)

    for deployment in discover_deployments():
        # whole deployment, so a test beside its subject is not missed
        for path in sorted(deployment.rglob("test_*.py")):
            if not _skipped(path):
                found.setdefault(path, f"deploy/{deployment.name}")

    return [(group, path) for path, group in found.items()]


def classify(rc: int, out: str, under_tests_dir: bool) -> tuple[str, str]:
    """Map a pytest exit code plus its output to ``(verdict, detail)``."""
    if rc == 0:
        return "PASS", ""
    if rc == 5:
        return "NOTESTS", "no pytest tests (standalone script?)"
    if rc in (-9, 137, 124):
        return "TIMEOUT", "killed"
    missing = MISSING_MODULE.search(out)
    if missing and rc == 2:
        mod = missing.group(1)
        # a first-party module going missing is a real break, not the environment
        if not mod.startswith("helao"):
            return "ENV", f"needs {mod}"
        return "FAIL", f"missing first-party module {mod}"
    fixture = MISSING_FIXTURE.search(out)
    if fixture and not under_tests_dir:
        # Production module whose name collides with pytest's convention: a
        # *test station* server whose endpoint registrar is `test_station_
        # endpoints(app)` reads as a test wanting an `app` fixture. Inside a
        # tests/ dir the same error IS a real bug, so the leniency is confined
        # to files outside one.
        return "NOTATEST", f"needs fixture {fixture.group(1)!r}; not a test module"
    return "FAIL", f"rc={rc}"


def summarize(out: str) -> str:
    seen: dict[str, int] = {}
    for n, kind in COUNTS.findall(out):
        kind = "error" if kind == "errors" else kind
        seen[kind] = seen.get(kind, 0) + int(n)
    order = ("passed", "failed", "error", "skipped", "xfailed", "xpassed")
    return " ".join(f"{seen[k]} {k}" for k in order if k in seen)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--timeout", type=int, default=150, help="per-file cap, seconds")
    ap.add_argument(
        "--filter", default=None, help="only paths containing this substring"
    )
    ap.add_argument("--list", action="store_true", help="list files, run nothing")
    args = ap.parse_args(argv)

    # Line-buffer stdout: this prints a line per file over several minutes, and
    # Python fully buffers when redirected to a file or pipe -- without this the
    # log stays empty until the run ends, which is exactly when progress stops
    # being useful.
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except (AttributeError, ValueError):  # non-reconfigurable stream
        pass

    files = discover_files()
    if args.filter:
        files = [(g, p) for g, p in files if args.filter in str(p)]
    if not files:
        print("no test files discovered")
        return 1

    if args.list:
        for group, path in files:
            print(f"{group:24} {path.relative_to(REPO_ROOT)}")
        print(f"\n{len(files)} files")
        return 0

    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    tally: dict[str, list[str]] = {}
    started = time.monotonic()
    group_now = None

    for group, path in files:
        if group != group_now:
            group_now = group
            print(f"\n--- {group}")
        rel = path.relative_to(REPO_ROOT)
        if not has_pytest_tests(path):
            # never handed to pytest: collection would import it and run its
            # module-level code
            tally.setdefault("NOTESTS", []).append(str(rel))
            print(f"  {'NOTESTS':8} {rel}  (no pytest tests; not imported)")
            continue
        proc = _run_capped(path, args.timeout, env)
        out = (proc.stdout or "") + (proc.stderr or "")
        verdict, detail = classify(
            proc.returncode, out, under_tests_dir="tests" in path.parts
        )
        tally.setdefault(verdict, []).append(str(rel))
        counts = summarize(out)
        note = f"  ({detail})" if detail else ""
        print(f"  {verdict:8} {rel}  {counts}{note}")
        if verdict == "FAIL":
            for line in out.splitlines():
                if line.startswith(("FAILED", "ERROR", "E   ")):
                    print(f"           {line[:160]}")

    elapsed = time.monotonic() - started
    print(f"\n===== {len(files)} files in {elapsed:.0f}s")
    for verdict in ("PASS", "ENV", "NOTESTS", "NOTATEST", "TIMEOUT", "FAIL"):
        names = tally.get(verdict, [])
        if not names:
            continue
        print(f"  {verdict:8} {len(names)}")
        if verdict in ("FAIL", "TIMEOUT"):
            for n in names:
                print(f"           {n}")
    failed = len(tally.get("FAIL", [])) + len(tally.get("TIMEOUT", []))
    print(f"\n{'FAILURES: ' + str(failed) if failed else 'ALL GREEN'}")
    return 1 if failed else 0


def _run_capped(path: Path, cap: int, env: dict) -> subprocess.CompletedProcess:
    """Run one file under a wall-clock cap, reporting a timeout as rc=124.

    ``cap <= 0`` disables the cap, which is only ever useful when hunting a hang
    interactively -- the default exists because a wedged file would otherwise
    stall the whole sweep.
    """
    try:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(path),
                "-q",
                "--color=no",
                "-p",
                "no:cacheprovider",
            ],
            capture_output=True,
            text=True,
            timeout=cap if cap > 0 else None,
            env=env,
            cwd=str(REPO_ROOT),
        )
    except subprocess.TimeoutExpired as exc:
        out = (
            (exc.stdout or b"") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        )
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return subprocess.CompletedProcess(exc.cmd, 124, out, "")


if __name__ == "__main__":
    sys.exit(main())
