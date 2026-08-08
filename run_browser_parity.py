"""Run the rendered-parity lane end to end: one command, one exit code.

Launches each config the lane needs, runs every browser check against it, tears
the group down, and diffs the legacy-hosted matrix against the hexagon-hosted
one. Exits non-zero if any check fails or the diff is non-empty, so the lane is
a single line in a gate or a station runbook rather than a procedure.

Usage::

    python run_browser_parity.py                 # the whole lane
    python run_browser_parity.py --lane bokeh    # one lane only
    python run_browser_parity.py --self-test     # harness self-checks, no launch
    python run_browser_parity.py --keep-running  # leave the last group up

Three things about running it that are not obvious, all of them learned by
getting them wrong first:

* **The conda environment must be on ``PATH``, not merely the interpreter.**
  ``launch.py`` spawns its children as a bare ``python``, so invoking it by
  absolute path starts a launcher that reports success while every child dies
  on ``ModuleNotFoundError``. This script puts the running interpreter's
  directory on ``PATH`` for the child.
* **Teardown is slow and must be waited for, by port.** ``SIGINT`` runs the
  same ordered shutdown ``CTRL-x`` does, which took 60-90 seconds in testing.
  Launching the next config before the previous one has released its ports
  produces a group that binds nothing and silently keeps serving the *old*
  processes' code.
* **``pgrep -f`` matches this script's own command line.** A readiness or
  teardown loop written against it never terminates, because the pattern is in
  the arguments of the process doing the matching. Readiness and teardown here
  are both decided by whether the ports are bound.

The Reflex lane needs a bundle built for the config's port, and the bundle must
be rebuilt whenever ``class_name=`` usage changed -- ``--build`` does that.
"""

__all__ = ["LANES", "launch_group", "run_lane", "stop_group", "wait_for_ports"]

import argparse
import os
import signal
import socket
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

#: Where a run's matrices and launch logs land.
#:
#: A dot-directory with its own ``.gitignore`` entry, not ``STATES/``. The repo
#: root has no ``STATES/`` rule -- a config's ``STATES`` lives under its own
#: ``root:``, not here -- so writing there would leave every run's output as
#: untracked noise in ``git status``, which is how generated files end up
#: committed by accident.
MATRIX_DIR = os.path.join(REPO_ROOT, ".browser-parity")

#: The lanes, in run order.
#:
#: ``pair`` names the other lane this one's matrix is diffed against. P7's claim
#: is that the graft moves the hosting and changes nothing rendered, so the
#: legacy-hosted and hexagon-hosted runs of the same documents must agree.
#:
#: **The Reflex lane has no pair, and that is a measured limitation rather than
#: an omission.** A hexagon-hosted Reflex variant does not exist yet:
#: ``helao/hexagon/app/ui_host.py``'s ``build_ui_app`` raises ``HexagonDeferred
#: ("Reflex hosting lands in P7f")``, and no config can select a hexagon Reflex
#: host. The Reflex half of the matrix diff becomes runnable when P7f lands --
#: add ``"pair": "reflex_hexagon"`` here and a config beside it. Everything
#: else about the Reflex lane (styles, pixels, both Q10 branches) runs today.
LANES = {
    "bokeh_legacy": {
        "config": "goldenvis",
        "check": "helao/core/tests/browser_parity/check_bokeh_docs.py",
        "args": ["goldenvis"],
        "ports": [5001, 5002, 5003, 8001, 8002, 8010],
        "pair": "bokeh_hexagon",
    },
    "bokeh_hexagon": {
        "config": "goldenhexgraft",
        "check": "helao/core/tests/browser_parity/check_bokeh_docs.py",
        "args": ["goldenhexgraft"],
        "ports": [5001, 5002, 5003, 8001, 8002, 8010],
    },
    "reflex": {
        "config": "goldenreflex",
        "check": "helao/core/tests/browser_parity/check_reflex_routes.py",
        "args": ["http://127.0.0.1:5010", "goldenreflex"],
        "ports": [5001, 5010, 5011, 8001, 8002, 8003, 8004],
        "needs_bundle": True,
    },
    "reflex_hte": {
        # The hte panels, and the only place P7i's potentiostat stop buttons
        # are reachable: Tailwind compiles only the utilities present in the
        # *exported* frontend, and a bundle built for `goldenreflex` contains
        # none of the hte panels. Measured -- `bg-red-700` appears 0 times in
        # the goldenreflex bundle's CSS and once in this one's.
        #
        # **This lane and `reflex` cannot share a bundle**, because the export
        # bakes the backend URL and these are different ports (5011 vs 5111).
        # Running both in one invocation therefore requires `--build`, and the
        # runner sequences them so each is measured against its own bundle.
        "config": "htereflex",
        "check": "helao/core/tests/browser_parity/check_reflex_routes.py",
        "args": ["http://127.0.0.1:5110", "htereflex"],
        "ports": [5110, 5111, 8101, 8102, 8106, 8110, 8111],
        "needs_bundle": True,
    },
    "aligner": {
        # No config and no group: the aligner's Bokeh Server is built inside an
        # action-server process, so P7d's ui_host port is what the check
        # composes directly. Nothing to launch, nothing to tear down.
        "config": None,
        "check": "helao/core/tests/browser_parity/check_aligner.py",
        "args": [],
        "ports": [],
    },
    "reflex_specs": {
        "config": "goldenreflexspec",
        "check": "helao/core/tests/browser_parity/check_reflex_routes.py",
        "args": ["http://127.0.0.1:5010", "goldenreflexspec"],
        "ports": [5010, 5011, 8001, 8002],
        # Same ports as `reflex`, deliberately: the exported bundle bakes the
        # backend URL, so a Q10 variant on a different port would need a second
        # bundle and would then be testing a different build.
        "needs_bundle": False,
    },
}


def port_is_bound(port: int, host: str = "127.0.0.1") -> bool:
    """Whether something is listening on *port*."""
    with socket.socket() as probe:
        probe.settimeout(0.4)
        return probe.connect_ex((host, port)) == 0


def wait_for_ports(ports: list, timeout: float, bound: bool) -> bool:
    """Block until every port is bound (or every port is free).

    Deciding readiness by port rather than by process is what keeps this
    correct: ``pgrep -f`` on the config prefix matches this script's own
    command line, so a process-based wait never finishes.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(port_is_bound(p) == bound for p in ports):
            return True
        time.sleep(2)
    return False


def launch_group(config: str, ports: list, log_path: str, timeout: float = 240):
    """Start one orchestration group and wait for it to bind its ports.

    Returns:
        subprocess.Popen: The launcher.

    Raises:
        RuntimeError: If the group did not come up, with the tail of its log --
            the useful part, since the launcher itself exits 0 in several of
            the ways a group can fail to start.
    """
    if not wait_for_ports(ports, 5, bound=False):
        held = [p for p in ports if port_is_bound(p)]
        raise RuntimeError(
            f"ports {held} are already bound; a previous group is still "
            f"running and a new one would silently keep serving its code"
        )
    environment = dict(os.environ)
    # `launch.py` spawns a bare `python`; without this its children die on
    # ModuleNotFoundError while the launcher reports success.
    environment["PATH"] = (
        os.path.dirname(sys.executable) + os.pathsep + environment.get("PATH", "")
    )
    environment["PYTHONPATH"] = REPO_ROOT
    handle = open(log_path, "w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "launch.py", config],
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=handle,
        stderr=subprocess.STDOUT,
        env=environment,
        start_new_session=True,
    )
    if not wait_for_ports(ports, timeout, bound=True):
        stop_group(process, ports)
        with open(log_path, encoding="utf-8") as log:
            tail = "".join(log.readlines()[-25:])
        raise RuntimeError(f"'{config}' did not bind {ports} in {timeout}s:\n{tail}")
    return process


def stop_group(process, ports: list, timeout: float = 180) -> bool:
    """Stop a group and wait for every port to be released.

    ``SIGINT`` to the launcher runs the same ordered teardown ``CTRL-x`` does.
    It is not fast -- 60-90 seconds is normal -- and the wait is mandatory:
    the next config in the lane binds the same ports.
    """
    if process.poll() is None:
        os.killpg(os.getpgid(process.pid), signal.SIGINT)
    released = wait_for_ports(ports, timeout, bound=False)
    if not released and process.poll() is None:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        released = wait_for_ports(ports, 30, bound=False)
    return released


def build_bundle(config: str) -> int:
    """Rebuild the Reflex bundle for *config*.

    Unconditional when asked for, not port-conditional: the compiled CSS
    contains only the utilities present at build time, so any slice that
    changed ``class_name=`` usage invalidates a bundle that still has the right
    port baked in. A stale bundle renders the new controls completely unstyled
    with no error on either side -- which is the failure this whole lane exists
    to catch, and it would be absurd to run the lane against one by accident.
    """
    print(f"[parity] building the Reflex bundle for {config}")
    return subprocess.call(
        [sys.executable, "build_reflex_bundle.py", config],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": REPO_ROOT},
    )


def run_lane(name: str, lane: dict, build: bool, keep: bool) -> tuple:
    """Launch, check, tear down. Returns ``(exit_code, matrix_path)``."""
    os.makedirs(MATRIX_DIR, exist_ok=True)
    matrix_path = os.path.join(MATRIX_DIR, f"{name}.json")
    log_path = os.path.join(MATRIX_DIR, f"{name}.launch.log")

    if build and lane.get("needs_bundle"):
        if build_bundle(lane["config"]) != 0:
            print(f"[parity] FAIL: bundle build for {lane['config']}")
            return 1, matrix_path

    command = [sys.executable, lane["check"], *lane["args"], "--json", matrix_path]
    if lane["config"] is None:
        # A lane that hosts its own document. Nothing to launch or tear down.
        print(f"[parity] running lane '{name}' with no orchestration group")
        code = subprocess.call(
            command, cwd=REPO_ROOT, env={**os.environ, "PYTHONPATH": REPO_ROOT}
        )
        return code, matrix_path

    print(f"[parity] launching {lane['config']} for lane '{name}'")
    process = launch_group(lane["config"], lane["ports"], log_path)
    try:
        code = subprocess.call(
            command, cwd=REPO_ROOT, env={**os.environ, "PYTHONPATH": REPO_ROOT}
        )
    finally:
        if keep:
            print(f"[parity] leaving {lane['config']} running as asked")
        elif not stop_group(process, lane["ports"]):
            print(f"[parity] WARNING: {lane['config']} did not release its ports")
            code = 1
    return code, matrix_path


def self_test() -> int:
    """Prove the harness can fail, without launching anything.

    Two properties, both of which a green lane depends on and neither of which
    a passing run demonstrates:

    * The **matrix diff reports a perturbation.** A diff that always comes back
      empty is indistinguishable from a diff that works, right up until it
      matters. This takes a real captured matrix, changes one value, and
      requires the diff to name exactly that key.
    * The **volatile-key list does not swallow a real key.** Every excluded key
      is a hole in the gate, so this asserts that a colour or a count is still
      compared after the exclusions are applied.
    """
    from helao.core.tests.browser_parity.matrix import (
        diff_matrices,
        load_matrix,
        perturb,
    )

    path = os.path.join(MATRIX_DIR, "bokeh_legacy.json")
    if not os.path.isfile(path):
        print(
            f"[parity] self-test needs a captured matrix at {path}; run the lane first"
        )
        return 1
    document = load_matrix(path)

    if diff_matrices(document, document):
        print("[parity] FAIL: a matrix differs from itself")
        return 1

    key = "operator.btn_danger_bg_rgb"
    mutated = perturb(document, key, [0, 0, 0])
    differences = diff_matrices(document, mutated)
    if [d[0] for d in differences] != [key]:
        print(f"[parity] FAIL: perturbing {key} produced {differences}")
        return 1
    print(f"[parity] self-test: perturbing {key} is reported, and nothing else is")

    # A volatile key must be ignored...
    volatile = "operator.doc_title"
    if diff_matrices(document, perturb(document, volatile, "something else")):
        print(f"[parity] FAIL: {volatile} should be excluded from the diff")
        return 1
    print(f"[parity] self-test: {volatile} is excluded, as declared")
    return 0


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", action="append", help="run only these lanes")
    parser.add_argument(
        "--build", action="store_true", help="rebuild the Reflex bundle first"
    )
    parser.add_argument(
        "--keep-running", action="store_true", help="leave the last group up"
    )
    parser.add_argument(
        "--self-test", action="store_true", help="harness self-checks only"
    )
    options = parser.parse_args()

    if options.self_test:
        return self_test()

    names = options.lane or list(LANES)
    unknown = [n for n in names if n not in LANES]
    if unknown:
        print(f"unknown lane(s): {unknown}; known: {list(LANES)}")
        return 2

    results = {}
    for index, name in enumerate(names):
        keep = options.keep_running and index == len(names) - 1
        code, path = run_lane(name, LANES[name], options.build, keep)
        results[name] = (code, path)
        print(f"[parity] lane '{name}' exited {code}")

    from helao.core.tests.browser_parity.matrix import (
        diff_matrices,
        format_diff,
        load_matrix,
    )

    failures = [n for n, (code, _) in results.items() if code != 0]
    for name in names:
        pair = LANES[name].get("pair")
        if not pair or pair not in results:
            continue
        differences = diff_matrices(
            load_matrix(results[name][1]), load_matrix(results[pair][1])
        )
        print(format_diff(name, pair, differences))
        if differences:
            failures.append(f"{name}-vs-{pair}")

    if failures:
        print(f"[parity] FAIL: {failures}")
        return 1
    print(f"[parity] PASS: {len(names)} lane(s), matrices agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
