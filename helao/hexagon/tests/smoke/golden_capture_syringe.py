"""Runtime golden-diff capture for the syringe_server hexagon canary (P3a
special-split).

*** READS A SOFTWARE VOLUME COUNTER -- NON-PERTURBING, HARDWARE-INDEPENDENT. ***

Step 0 of the parent task investigated ``get_present_volume`` and found it is
fundamentally different from the galil/gamry/spec reads:

``get_present_volume`` (``POST /WORKSYRINGE/get_present_volume``,
syringe_server.py) reads the KDS100 driver's **software-tracked**
``present_volume_ul`` attribute, writes it into the -act.yml action_params as
``_present_volume_ul`` (exactly as galil query_positions writes ``_positions``),
enqueues ONE .hlo data row (columns ``present_volume_ul`` + ``error_code``),
and finishes. ``present_volume_ul`` is initialized to ``0.0`` in
``KDS100.__init__`` (legato_driver.py) and is mutated ONLY by
infuse/withdraw (``clear_volume`` with a non-zero direction, in PumpExec
_post_exec) or the private ``set_present_volume`` endpoint. ``connect()`` opens
the pyserial COM port but NEVER reads the volume off the wire. So on a FRESH
launch, before any dispense action, the value is deterministically ``0.0`` --
and ``get_present_volume`` returns that Python attribute, NOT a device query.

Two consequences, both distinct from galil/gamry/spec:

  1. **No masking.** Both the -act.yml ``_present_volume_ul`` leaf and the .hlo
     ``present_volume_ul`` / ``error_code`` columns are deterministic on a fresh
     idle pump (``0.0`` / ``ErrorCodes.none``). They are NOT live/nondeterministic
     device readings, so masked_meta_keys / masked_hlo_columns are EMPTY here
     (masking a deterministic value would only weaken the parity check). Any
     legacy-vs-hexagon difference in these values is therefore a REAL regression
     and is compared unmasked. Contrast galil (``position`` is a live encoder
     read -> masked_hlo_columns) and gamry (``*_mean_final`` are live-measurement
     derived -> masked_meta_keys).

  2. **Hardware-independent.** Because the read never touches the wire, this
     capture produces a valid, non-vacuous, exactly-reproducible tree even with
     the Legato pump DETACHED (or on Linux, where COM5 does not exist and
     connect() just fails soft). ``check_device_open`` below therefore only WARNS
     (it does not raise like galil's verify_device_open): a closed serial port
     does not invalidate a get_present_volume capture, it just means the driver's
     full serial lifecycle wasn't exercised.

``get_present_volume`` is NON-PERTURBING regardless: it issues no infuse/
withdraw/run command and does not move the plunger or fluid (contrast infuse/
withdraw, which drive the pump -- deliberately NOT chosen for this canary).

Standalone counterpart to ``harness.capture.snapshot_capture`` for the
orch-less, db-less syringe/syringehex 2-server topology (WORKSYRINGE@8013 +
ACTVIS@5001 only -- no ORCH, no DB), mirroring galil's
``helao.hexagon.tests.smoke.golden_capture_galil`` and gamry's
``golden_capture`` (see those modules for the full topology-gap rationale). The
hardware-agnostic settle/anti-vacuous-guard logic (``settle``,
``_run_artifacts``, ``_act_status_map``, ``dispatch_action``) is IMPORTED from
``golden_capture.py`` -- it is pure -act.yml/RUNS_ACTIVE polling logic with no
scenario-specific assumptions. Only the scenario-specific pieces (endpoint,
masking=NONE, manifest notes) are new here. ``golden_capture.py`` is NOT modified.

Usage (conda env ``helao``) -- the Legato pump need NOT be attached for a valid
capture, and THE PLUNGER DOES NOT MOVE for this scenario:

    rmdir /s /q C:\\INST_hlo_golden               (or pick a fresh --root)
    conda run -n helao python launch.py syringegold --no-hot-reload
    conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_syringe ^
        --config-prefix syringegold --root C:\\INST_hlo_golden ^
        --out C:\\golden\\syringe

then terminate the launch, point ``--root``/``--config-prefix`` at a FRESH
throwaway root and ``syringegoldhex``, capture again, and diff the two capture
directories with ``harness.parity``. ``syringe_diff.bat`` automates exactly
this sequence.
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import subprocess
import sys
from pathlib import Path

import requests

from harness import HARNESS_VERSION
from harness.capture import assert_fresh, wait_for_server
from harness.manifest import ProvenanceManifest
from harness.treepass import PARITY_TOPS

from helao.hexagon.tests.smoke.golden_capture import (
    _act_status_map,
    _run_artifacts,
    dispatch_action,
    settle,
)

SYRINGE_HOST, SYRINGE_PORT = "127.0.0.1", 8013

SCENARIO = "GM-SYRVOL"

# helao/hexagon/tests/smoke/golden_capture_syringe.py -> repo root is 4 parents
# up (matches safe_root.py's own _repo_root()).
REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = REPO_ROOT / "helao" / "deploy" / "hte" / "configs"

# MASKING = NONE (deliberate -- see module docstring). get_present_volume
# writes the driver's software-tracked present_volume_ul (0.0 on a fresh idle
# pump) into:
#   - -act.yml action_params ._present_volume_ul  (deterministic 0.0)
#   - one .hlo row: present_volume_ul (0.0) + error_code (ErrorCodes.none)
# All three are config-deterministic on a fresh launch, NOT live/nondeterministic
# device readings, so nothing is masked. Any legacy-vs-hexagon diff on them is a
# REAL regression. These are exported (empty) so the unit test can assert the
# masking decision explicitly -- a future edit that adds masking here must be a
# conscious change that flips the test.
SYRVOL_MASKED_HLO_COLUMNS: dict = {}
SYRVOL_MASKED_META_KEYS: dict = {}


def check_device_open(host: str, port: int) -> bool:
    """WARN (do NOT raise) if the KDS100 serial port did not open at startup.

    ``KDS100.connect()`` opens the pyserial COM port; if it is unreachable
    (pump detached, wrong COM, or Linux where COM5 does not exist) connect()
    catches the exception and returns a failed ``DriverResponse`` WITHOUT
    raising, so the server still comes up with ``self.com is None`` and
    ``KDS100.get_status()`` reports ``uninitialized``.

    Unlike galil's ``verify_device_open`` (which HARD-RAISES because
    query_positions returns empty data off a closed controller), this check is
    NON-FATAL: ``get_present_volume`` reads the software-tracked
    ``present_volume_ul`` attribute (0.0 on a fresh launch), NOT the wire, so it
    produces a valid, deterministic, non-vacuous capture even with the serial
    port closed. A closed port only means the driver's full serial lifecycle was
    not exercised -- worth a loud warning, not an abort.

    NOTE: ``get_status`` is a PRIVATE endpoint -- bare ``/get_status``, NOT
    ``/WORKSYRINGE/get_status``. On this server only ACTION endpoints carry the
    ``/{server_key}/`` prefix (e.g. ``/WORKSYRINGE/get_present_volume``);
    private/system routes (get_status, shutdown, endpoints) are unprefixed.
    ``_driver_status`` is ``KDS100.get_status()``'s ``DriverStatus`` value:
    "uninitialized" when ``self.com`` is None, "ok" once the serial port is open
    (base_api.py's bare ``/get_status`` handler appends it as
    ``status_dict["_driver_status"]``).

    Returns True if the device serial port is open, else False (after warning).
    """
    try:
        r = requests.post(f"http://{host}:{port}/get_status", timeout=10)
        driver_status = r.json().get("_driver_status") if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        driver_status = None
    if driver_status not in ("ok", "busy"):
        print(
            f"[golden_capture_syringe] WARNING: WORKSYRINGE serial port is NOT "
            f"open (_driver_status={driver_status!r}) -- connect() failed at "
            "startup (pump detached / wrong COM / Linux with no COM5). This does "
            "NOT invalidate the capture: get_present_volume reads the software "
            "present_volume_ul counter (0.0 on a fresh launch), not the wire, so "
            "the tree is still valid and deterministic. Attach the pump if you "
            "want to exercise the full serial driver lifecycle."
        )
        return False
    return True


def get_present_volume_action(config_prefix: str) -> dict:
    """Run /WORKSYRINGE/get_present_volume via ``async_action_dispatcher`` (the
    production action-dispatch path -- RPC then HTTP, full action envelope).

    No params: ``get_present_volume`` takes none. Non-perturbing -- reads the
    tracked ``present_volume_ul`` counter only, issues no pump motion command.
    """
    return dispatch_action(config_prefix, "WORKSYRINGE", "get_present_volume")


def snapshot(
    root: Path,
    out_dir: Path,
    config_prefix: str,
    notes: str = "",
) -> Path:
    """Copy PARITY_TOPS from ``root`` and write a provenance manifest.

    Refuses to overwrite an existing ``out_dir``, matching
    ``harness.capture.snapshot_capture`` / galil's ``golden_capture_galil.snapshot``.
    """
    root, out_dir = Path(root), Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(
            f"{out_dir} already exists; refusing to overwrite a capture"
        )
    # Anti-vacuous-pass guard (shared with galil/gamry): an empty capture (no
    # action output) compares to nothing and passes parity trivially. Require at
    # least one -act.yml before writing anything.
    #
    # For THIS scenario a .hlo IS expected (get_present_volume always enqueues
    # one data row and finishes -- it is NOT metadata-only), so a missing .hlo is
    # a strong signal of a broken data-write path and is warned loudly below.
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
            f"[golden_capture_syringe] WARNING: {len(errored)} action(s) ERRORED "
            f"and were still captured: {errored}. An errored run is NOT a valid "
            "parity baseline (it likely produced no data / partial output). Check "
            "the -act.yml error fields and the WORKSYRINGE log before trusting a "
            "PASS."
        )
    if not hlos:
        print(
            f"[golden_capture_syringe] WARNING: no .hlo captured under {root} -- "
            "get_present_volume ALWAYS enqueues one data row, so its absence "
            "means the data-write path did not run. Parity will compare -act.yml "
            "metadata only, NOT the hlo data-write path. Check the WORKSYRINGE "
            "log."
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
        "get_present_volume capture: reads the KDS100 driver's software-tracked "
        "present_volume_ul counter (0.0 on a fresh launch, KDS100.__init__), NOT "
        "a wire query -- NON-PERTURBING (no plunger motion) and "
        "hardware-INDEPENDENT (valid even with the pump detached). The -act.yml "
        "_present_volume_ul leaf and the .hlo present_volume_ul/error_code "
        "columns are config-deterministic on a fresh idle pump, so NOTHING is "
        "masked (masking a deterministic value would only weaken the parity "
        "check); any legacy-vs-hexagon diff on them is a REAL regression."
    )
    if notes:
        combined_notes = f"{combined_notes} {notes}"
    ProvenanceManifest(
        scenario=SCENARIO,
        config_prefix=config_prefix,
        config_path=str(config_path),
        legacy_git_sha=sha,
        launch_cmd=f"conda run -n helao python launch.py {config_prefix} --no-hot-reload",
        sequence_name="manual_get_present_volume",
        sequence_params={
            "manual": True,
            "endpoint": "POST /WORKSYRINGE/get_present_volume",
        },
        capture_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=SYRVOL_MASKED_HLO_COLUMNS,
        masked_meta_keys=SYRVOL_MASKED_META_KEYS,
        notes=combined_notes,
    ).save(out_dir)
    return out_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helao.hexagon.tests.smoke.golden_capture_syringe",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config-prefix", required=True)
    parser.add_argument("--settle-polls", type=int, default=3)
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    assert_fresh(args.root)
    wait_for_server(SYRINGE_HOST, SYRINGE_PORT)
    check_device_open(SYRINGE_HOST, SYRINGE_PORT)  # non-fatal warning only
    get_present_volume_action(args.config_prefix)
    settle(args.root, settle_polls=args.settle_polls)
    out = snapshot(
        root=args.root,
        out_dir=args.out,
        config_prefix=args.config_prefix,
        notes=args.notes,
    )
    print(f"captured {SCENARIO} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
