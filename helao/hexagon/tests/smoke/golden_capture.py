"""Runtime golden-diff capture for the gamry hexagon canary (P3a special-split).

*** DRIVES THE REAL POTENTIOSTAT. THIS IS NOT A SIMULATION. ***

Step 0 of the parent task investigated whether ``run_OCV`` can produce data
under ``simulation: true``/``dummy: true`` with no real potentiostat attached,
and found: no. ``GamryDriver.__init__`` (helao/deploy/hte/drivers/pstat/gamry/
driver.py) unconditionally opens a real GamryCOM connection, and
``gamry_server2.py`` instantiates ``driver_classes=[GamryDriver]``
unconditionally -- there is no dummy/sim driver swap anywhere in this code
path. The config's ``dummy``/``simulation`` YAML keys are cosmetic (banner
color) for this canary only.

This capture rig is therefore an AT-STATION, REAL-HARDWARE gate. Before
running it, the operator MUST attach a dummy cell / calibration resistor to
the potentiostat -- ``run_OCV`` (open-circuit voltage monitoring, ``CellMon``,
non-perturbing) is safe against a dummy cell and never actively drives it,
but it still requires a live GamryCOM device to produce any data at all.

Standalone counterpart to ``harness.capture.snapshot_capture`` for the
orch-less, db-less gamry/gamryhex 2-server topology (PSTAT@8001 + ACTVIS@5001
only -- no ORCH, no DB). ``harness.capture``'s ``quiesce``/``orch_stopped``/
``db_drained`` assume an orchestrator + DB server and do not apply here (see
the rationale already recorded in ``gamryhex_canary.bat``, which hit the same
topology gap for the openapi-diff canary). Settling gates on the action's -act.yml reaching a
TERMINAL ``action_status`` (finished/errored) -- NOT on the file existing,
because a manual action writes its -act.yml at init with status "active"
(base.py:1029) and only rewrites it terminal at finish; settling on existence
would snapshot + kill the server mid-measurement.

Usage (AT-STATION, Windows, conda env ``helao``) -- ATTACH THE DUMMY CELL /
CAL RESISTOR FIRST:

    rmdir /s /q C:\\INST_hlo_golden               (or pick a fresh --root)
    conda run -n helao python launch.py gamrygold --no-hot-reload
    conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture ^
        --config-prefix gamrygold --root C:\\INST_hlo_golden ^
        --out C:\\golden\\gamry

then terminate the launch, point ``--root``/``--config-prefix`` at a FRESH
throwaway root and ``gamrygoldhex``, capture again, and diff the two capture
directories with ``harness.parity``. ``golden_diff.bat`` automates exactly
this sequence.
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

from harness import HARNESS_VERSION
from harness.capture import assert_fresh, runs_active_empty, wait_for_server
from harness.manifest import ProvenanceManifest
from harness.treepass import PARITY_TOPS
from harness.yaml_pass import load_yml_plain

# HloStatus terminal states. A manual action's -act.yml is written at init with
# status "active" (base.py:1029 update_act_file) and only REWRITTEN with a
# terminal status at finish (write_act). Settling on the file's mere existence
# therefore snapshots + kills mid-measurement; settle on a terminal status.
TERMINAL_STATUSES = ("finished", "errored")

PSTAT_HOST, PSTAT_PORT = "127.0.0.1", 8001

SCENARIO = "GM-OCV"

# helao/hexagon/tests/smoke/golden_capture.py -> repo root is 4 parents up
# (matches safe_root.py's own _repo_root()).
REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = REPO_ROOT / "helao" / "deploy" / "hte" / "configs"

# helao/deploy/hte/drivers/pstat/gamry/dtaq.py: DTAQ_OCV.output_keys. These
# are raw ADC/COM samples pulled straight off the live potentiostat -- no
# seeded/deterministic sim values exist anywhere in this driver -- so their
# VALUES must be masked for parity; row counts are compared within a small
# tolerance (PumpEvents/dtaq-sink timing jitters run to run).
OCV_HLO_COLUMNS = [
    "t_s",
    "Ewe_V",
    "Vm",
    "Vsig",
    "Ach_V",
    "Overload_HEX",
    "StopTest",
    "unknown1",
    "unknown2",
    "unknown3",
]
OCV_MASKED_HLO_COLUMNS = {
    "*OCV*.hlo": OCV_HLO_COLUMNS,
    "*OCV*.hlo.json*": OCV_HLO_COLUMNS,
}
OCV_HLO_ROW_COUNT_TOLERANCE = {"*OCV*.hlo": 2, "*OCV*.hlo.json*": 2}
# Any csv postprocess derived from the masked columns above: line-count only.
OCV_CONTENT_MASKED_FILES = {"*.csv": "line-count"}

# GamryExec._post_exec (gamry_server2.py ~283-330) writes data-derived summary
# values into the run's -act.yml action_params: t_s__mean_final,
# Ewe_V__mean_final, and (run_OCV only) has_bubble. These derive from the exact
# same live/unmasked measurement and are NOT covered by masked_hlo_columns
# (which masks .hlo files only) nor by harness.yaml_pass.normalize_meta's §5.5
# volatile lists (they are plain float/bool leaves under action_params, not
# uuids/timestamps/host-identity). Without masking, harness.parity's diff_meta
# would report a diff on these three keys between any two independent captures,
# even against the identical dummy cell.
#
# They are masked via the manifest's masked_meta_keys (the meta-side analogue
# of masked_hlo_columns): parity neutralizes their VALUES on both sides before
# diffing while keeping the keys present, so the runtime diff is a CLEAN PASS
# when only these values differ, and a real regression in ANY other key/file
# still surfaces normally. Pattern is "*-act.yml" (any action yml in this
# GM-OCV capture set); the keys are no-ops on any yml lacking them.
OCV_ACT_YML_MASKED_META_KEYS = {
    "*-act.yml": [
        "action_params.t_s__mean_final",
        "action_params.Ewe_V__mean_final",
        "action_params.has_bubble",
    ],
}


def verify_device_open(host: str, port: int) -> None:
    """Fail fast if the potentiostat COM device did not connect at startup.

    GamryDriver.connect() opens an exclusive COM handle; if another gamry
    process holds dev_id the open raises ``CGamryPstat - In use by another
    script`` and the server comes up with a closed pstat. Running run_OCV then
    just errors with no data (an errored -act.yml, no .hlo). Checking
    ``/PSTAT/gamry_is_open`` (pstat.TestIsOpen) up front surfaces the real cause
    instead.
    """
    try:
        r = requests.post(f"http://{host}:{port}/PSTAT/gamry_is_open", timeout=10)
        is_open = r.status_code == 200 and bool(r.json())
    except (requests.RequestException, ValueError):
        is_open = False
    if not is_open:
        raise RuntimeError(
            "PSTAT gamry device is NOT open -- connect() failed at server "
            "startup (commonly 'CGamryPstat - In use by another script'). "
            "Another process holds the potentiostat: close the production gamry "
            "group, the openapi canary, and any leftover python / GamryCOM.exe, "
            "then re-run. See the PSTAT launch log for the connect traceback."
        )


def run_ocv_action(host: str, port: int, tval_s: float, acq_s: float) -> dict:
    """POST /PSTAT/run_OCV and return the dispatch response (does not block)."""
    r = requests.post(
        f"http://{host}:{port}/PSTAT/run_OCV",
        params={"Tval__s": tval_s, "AcqInterval__s": acq_s},
        json={"fast_samples_in": []},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _run_artifacts(root: Path) -> tuple:
    """(-act.yml paths, .hlo paths) anywhere under root's captured run trees."""
    root = Path(root)
    return (
        sorted(str(p) for p in root.rglob("*-act.yml")),
        sorted(str(p) for p in root.rglob("*.hlo")),
    )


def _act_status_map(root: Path) -> dict:
    """{-act.yml path: action_status list}. A file that is missing/partial/
    unreadable (mid-write) yields [] -> treated as not-yet-terminal."""
    out: dict = {}
    for a in Path(root).rglob("*-act.yml"):
        try:
            data = load_yml_plain(a)
            st = data.get("action_status") or []
        except Exception:
            st = []
        if isinstance(st, str):
            st = [st]
        out[str(a)] = list(st)
    return out


def _actions_complete(root: Path) -> bool:
    """True iff >=1 -act.yml exists and EVERY -act.yml has a terminal status.

    The -act.yml is written at action init with status "active" and only
    rewritten terminal at finish, so file existence alone is NOT completion.
    """
    m = _act_status_map(root)
    if not m:
        return False
    return all(any(s in TERMINAL_STATUSES for s in sts) for sts in m.values())


def settle(
    root: Path,
    settle_polls: int = 3,
    poll_s: float = 2.0,
    timeout_s: float = 300.0,
) -> None:
    """Wait for the run_OCV action to WRITE its -act.yml and FINISH, then settle.

    NO orch/DB in this topology, AND a manual direct-POST action writes to
    RUNS_DIAG (base.py:1016) and never touches RUNS_ACTIVE -- so polling
    ``runs_active_empty`` alone returns before any file is written,
    snapshotting an empty tree that then passes parity vacuously (the original
    at-station false PASS). Instead require the action's ``-act.yml`` to be
    present (the action ran to completion), ``RUNS_ACTIVE`` empty (nothing in
    flight), and the artifact count stable across ``settle_polls`` consecutive
    polls. If no ``-act.yml`` ever appears the action errored -> TimeoutError
    (loud failure, never a silent empty capture).

    Completion is gated on the -act.yml's action_status reaching a TERMINAL
    state (finished/errored), NOT on the file merely existing -- the file is
    written at init with status "active" (base.py:1029), so existence-based
    settling snapshots + kills the server MID-MEASUREMENT (observed: a captured
    -act.yml frozen at "active"). Also require RUNS_ACTIVE empty and the
    artifact count stable across ``settle_polls`` consecutive polls.

    NOTE: ``.hlo`` presence is intentionally NOT required here (a run that
    errors emits none); snapshot() warns about a missing/errored result
    instead, so settling never hangs on it.
    """
    root = Path(root)
    t0 = time.time()
    stable = 0
    last = None
    while time.time() - t0 < timeout_s:
        acts, hlos = _run_artifacts(root)
        count = len(acts) + len(hlos)
        ready = _actions_complete(root) and runs_active_empty(root)
        if ready and count == last:
            stable += 1
        elif ready:
            stable = 1
        else:
            stable = 0
        if stable >= settle_polls:
            return
        last = count
        time.sleep(poll_s)
    statuses = _act_status_map(root)
    raise TimeoutError(
        f"{root}: run_OCV did not reach a terminal action_status after "
        f"{timeout_s}s (statuses={statuses}). The action is stuck active or "
        "never wrote -- check the launch/capture logs. Refusing to snapshot a "
        "mid-flight tree."
    )


def snapshot(
    root: Path,
    out_dir: Path,
    config_prefix: str,
    tval_s: float,
    acq_s: float,
    notes: str = "",
) -> Path:
    """Copy PARITY_TOPS from ``root`` and write a provenance manifest.

    Refuses to overwrite an existing ``out_dir``, matching
    ``harness.capture.snapshot_capture``.
    """
    root, out_dir = Path(root), Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(
            f"{out_dir} already exists; refusing to overwrite a capture"
        )
    # Anti-vacuous-pass guard: an empty capture (no action output) compares to
    # nothing and passes parity trivially. Require at least one -act.yml before
    # writing anything, so a false PASS is impossible even if settle() were
    # bypassed. .hlo is NOT required (manual run_OCV may emit none), but its
    # absence is warned loudly: parity then compares -act.yml metadata only, not
    # the hlo data-write path.
    acts, hlos = _run_artifacts(root)
    if not acts:
        raise RuntimeError(
            f"{root} has no -act.yml to capture; refusing a vacuous capture "
            "that would pass parity with 0 diffs. Check the launch/capture "
            "logs -- the action may have errored or produced no output."
        )
    errored = [p for p, st in _act_status_map(root).items() if "errored" in st]
    if errored:
        print(
            f"[golden_capture] WARNING: {len(errored)} action(s) ERRORED and were "
            f"still captured: {errored}. An errored run is NOT a valid parity "
            "baseline (it likely produced no data / partial output). Check the "
            "-act.yml error fields and the PSTAT log before trusting a PASS."
        )
    if not hlos:
        print(
            f"[golden_capture] WARNING: no .hlo captured under {root} -- run_OCV "
            "produced no streamed data file. Parity will compare -act.yml "
            "metadata only, NOT the hlo data-write path. Verify the measurement "
            "actually acquires data (dummy cell connected, driver.get_data "
            "returning samples)."
        )
    out_root = out_dir / "root"
    out_root.mkdir(parents=True)
    for top in PARITY_TOPS:
        src = root / top
        if src.is_dir():
            shutil.copytree(src, out_root / top)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    config_path = CONFIG_DIR / f"{config_prefix}.yml"
    combined_notes = (
        "REAL-HARDWARE run_OCV capture (dummy cell / cal resistor at-station); "
        "NOT a simulation -- GamryDriver has no sim/dummy data path. -act.yml "
        "action_params t_s__mean_final, Ewe_V__mean_final, has_bubble are "
        "data-derived from the live measurement and are masked via "
        "masked_meta_keys so parity is a clean PASS when only they differ."
    )
    if notes:
        combined_notes = f"{combined_notes} {notes}"
    ProvenanceManifest(
        scenario=SCENARIO,
        config_prefix=config_prefix,
        config_path=str(config_path),
        legacy_git_sha=sha,
        launch_cmd=f"conda run -n helao python launch.py {config_prefix} --no-hot-reload",
        sequence_name="manual_run_OCV",
        sequence_params={
            "manual": True,
            "endpoint": "POST /PSTAT/run_OCV",
            "Tval__s": tval_s,
            "AcqInterval__s": acq_s,
            "fast_samples_in": [],
        },
        capture_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=OCV_MASKED_HLO_COLUMNS,
        hlo_row_count_tolerance=OCV_HLO_ROW_COUNT_TOLERANCE,
        content_masked_files=OCV_CONTENT_MASKED_FILES,
        masked_meta_keys=OCV_ACT_YML_MASKED_META_KEYS,
        notes=combined_notes,
    ).save(out_dir)
    return out_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helao.hexagon.tests.smoke.golden_capture",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config-prefix", required=True)
    parser.add_argument(
        "--tval", type=float, default=3.0, help="Tval__s (default 3.0s)"
    )
    parser.add_argument("--acq", type=float, default=0.1, help="AcqInterval__s")
    parser.add_argument("--settle-polls", type=int, default=3)
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    assert_fresh(args.root)
    wait_for_server(PSTAT_HOST, PSTAT_PORT)
    verify_device_open(PSTAT_HOST, PSTAT_PORT)
    run_ocv_action(PSTAT_HOST, PSTAT_PORT, args.tval, args.acq)
    settle(args.root, settle_polls=args.settle_polls)
    out = snapshot(
        root=args.root,
        out_dir=args.out,
        config_prefix=args.config_prefix,
        tval_s=args.tval,
        acq_s=args.acq,
        notes=args.notes,
    )
    print(f"captured {SCENARIO} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
