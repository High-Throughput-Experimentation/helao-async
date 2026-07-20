"""Runtime golden-diff capture for the galil_io hexagon canary (P3a
special-split).

*** DRIVES THE REAL GALIL IO CONTROLLER (READ-ONLY DIGITAL INPUT, NO
ACTUATION). ***

Step 0 of the parent task investigated whether ``get_digital_in`` needs a
live controller to produce data and found: yes, and more strictly than
galil_motion. ``Galil.connect()`` (helao/deploy/hte/drivers/io/
galil_io_driver.py) unconditionally opens a real ``gclib`` TCP connection to
``galil_ip_str`` and swallows any connection failure into
``galil_enabled = False`` (no exception propagates, no dummy/sim data path
anywhere in this code path) -- exactly like galil_motion. UNLIKE
galil_motion's ``query_positions`` (which is always registered and merely
returns empty position data when disconnected), ``galil_io.py``'s
``galil_dyn_endpoints`` gates its ENTIRE endpoint set -- including
``get_digital_in`` -- on ``app.driver.galil_enabled is True``
(galil_io.py:55). If the controller is unreachable at startup, the route
does not exist at all (a POST to it 404s) rather than returning empty/vacuous
data. The config's ``dummy``/``simulation`` YAML keys are therefore cosmetic
(banner color) for this canary, exactly as already documented for gamry in
``golden_capture.py`` and for galil_motion in ``golden_capture_galil.py``.

``get_digital_in`` (``POST /IO/get_digital_in``) is NON-PERTURBING: it reads
a digital input line via a ``MG @IN[n]`` gclib query and never writes to any
output (no ``set_digital_out``/``set_analog_out``/``set_digital_cycle``). It
is therefore safe to run at-station without actuating any pump/valve/LED
wired to ``dev_do``, but the galil controller must still be powered on and
reachable at ``galil_ip_str`` to produce any reading at all (and, per the
gating above, for the endpoint to exist). The pinned scenario reads
``di_item="gamry_ttl0"`` (port 1 in eche10's IO config) -- an existing input
line, never a ``dev_do`` output.

Standalone counterpart to ``harness.capture.snapshot_capture`` for the
orch-less, db-less galilio/galiliohex 2-server topology (IO@8005 +
ACTVIS@5001 only -- no ORCH, no DB), mirroring gamry's
``helao.hexagon.tests.smoke.golden_capture`` and galil_motion's
``golden_capture_galil`` (see those modules' docstrings for the full
topology-gap rationale already recorded there and in ``galil_canary.bat`` /
``gamryhex_canary.bat``, which hit the same gap for their openapi-diff
canaries). The hardware-agnostic settle/anti-vacuous-guard logic (``settle``,
``_run_artifacts``, ``_act_status_map``) is IMPORTED from
``golden_capture.py`` rather than re-implemented here -- it is pure
-act.yml/RUNS_ACTIVE polling logic with no gamry-specific assumptions (does
not reference gamry's OCV scenario name or masking). Only the
scenario-specific pieces (endpoint, masking, manifest notes) are new in this
module. ``golden_capture.py`` itself is NOT modified.

Usage (AT-STATION, Windows, conda env ``helao``) -- the galil controller must
be powered on and reachable at ``galil_ip_str`` (192.168.200.234 by default).
NO pump/valve/LED is actuated for this scenario (only a digital INPUT is
read):

    rmdir /s /q C:\\INST_hlo_golden               (or pick a fresh --root)
    conda run -n helao python launch.py galiliogold --no-hot-reload
    conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_galil_io ^
        --config-prefix galiliogold --root C:\\INST_hlo_golden ^
        --out C:\\golden\\galilio

then terminate the launch, point ``--root``/``--config-prefix`` at a FRESH
throwaway root and ``galiliogoldhex``, capture again, and diff the two
capture directories with ``harness.parity``. ``galilio_diff.bat`` automates
exactly this sequence.
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

IO_HOST, IO_PORT = "127.0.0.1", 8005

SCENARIO = "GM-DIN"

DI_ITEM = "gamry_ttl0"

# helao/hexagon/tests/smoke/golden_capture_galil_io.py -> repo root is 4
# parents up (matches safe_root.py's own _repo_root()).
REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = REPO_ROOT / "helao" / "deploy" / "hte" / "configs"

# galil_io.py's get_digital_in endpoint calls `Galil.get_digital_in(di_name=
# di_item)` and enqueues its return dict verbatim via `enqueue_data_dflt`
# (base.py writes datadict keys straight through as hlo columns -- see
# active_data_stream.py enqueue_data_dflt). get_digital_in
# (galil_io_driver.py) returns {"error_code": ..., "port": ..., "name": ...,
# "type": "digital_in", "value": ...}:
#   - "error_code"/"port"/"name"/"type": deterministic given the configured
#     di_item (ErrorCodes.none on every successful read, the configured port
#     number, the resolved channel name, and the literal "digital_in") --
#     NOT masked.
#   - "value": the live digital-input reading off the controller -- MASKED.
#     Tolerance 0: a single `enqueue_data_dflt` call writes exactly one row
#     (no poll loop / no jitter to tolerate).
DIN_HLO_COLUMNS = ["value"]
DIN_MASKED_HLO_COLUMNS = {
    "*get_di*.hlo": DIN_HLO_COLUMNS,
    "*get_di*.hlo.json*": DIN_HLO_COLUMNS,
}
DIN_HLO_ROW_COUNT_TOLERANCE = {
    "*get_di*.hlo": 0,
    "*get_di*.hlo.json*": 0,
}


def verify_device_open(host: str, port: int) -> None:
    """Fail fast if the Galil controller did not connect at startup.

    ``Galil.connect()`` opens a gclib TCP connection to ``galil_ip_str``; if
    the controller is unreachable or the open raises, ``connect()`` catches
    the exception and sets ``galil_enabled = False`` (see
    galil_io_driver.py), so the server otherwise comes up cleanly with a
    closed IO connection. UNLIKE galil_motion, ``galil_io.py``'s
    ``galil_dyn_endpoints`` gates its entire endpoint set (including
    ``get_digital_in``) on ``galil_enabled`` -- so a disconnected controller
    means ``POST /IO/get_digital_in`` returns 404, not empty data. Checking
    ``_driver_status`` up front surfaces the real cause instead of an
    opaque 404.

    NOTE: ``get_status`` is a PRIVATE endpoint -- bare ``/get_status``, NOT
    ``/IO/get_status``. On this server only ACTION endpoints carry the
    ``/{server_key}/`` prefix (e.g. ``/IO/get_digital_in``); private/system
    routes (get_status, shutdown, endpoints) are unprefixed. ``_driver_status``
    is ``Galil.get_status()``'s ``DriverStatus`` value: "uninitialized" when
    ``galil_enabled`` is falsy, "ok"/"busy" once the gclib connection is open
    (base_api.py's bare ``/get_status`` handler appends it as
    ``status_dict["_driver_status"]``).
    """
    try:
        r = requests.post(f"http://{host}:{port}/get_status", timeout=10)
        driver_status = r.json().get("_driver_status") if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        driver_status = None
    if driver_status not in ("ok", "busy"):
        raise RuntimeError(
            f"IO galil device is NOT open (_driver_status={driver_status!r}) "
            "-- connect() failed at server startup (commonly the "
            "galil_ip_str controller unreachable/powered off). Verify the "
            "Galil controller is powered on and reachable at the configured "
            "galil_ip_str, then re-run. See the IO launch log for the "
            "connect traceback."
        )


def get_digital_in_action(config_prefix: str) -> dict:
    """Run /IO/get_digital_in via ``async_action_dispatcher`` (the production
    action-dispatch path -- RPC then HTTP, full action envelope).

    ``di_item`` MUST travel in the action envelope's ``action_params``: the
    endpoint reads ``action.action_params["di_item"]``, so a bare
    ``private_dispatcher`` (empty envelope, param only in the query string)
    left ``action_params`` without ``di_item`` -> KeyError/500. Pinned to
    ``di_item="gamry_ttl0"`` -- a digital INPUT read, never a ``dev_do``
    output -- so this never actuates a pump/valve/LED.
    """
    return dispatch_action(config_prefix, "IO", "get_digital_in", {"di_item": DI_ITEM})


def snapshot(
    root: Path,
    out_dir: Path,
    config_prefix: str,
    notes: str = "",
) -> Path:
    """Copy PARITY_TOPS from ``root`` and write a provenance manifest.

    Refuses to overwrite an existing ``out_dir``, matching
    ``harness.capture.snapshot_capture`` / gamry's ``golden_capture.snapshot``.
    """
    root, out_dir = Path(root), Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(
            f"{out_dir} already exists; refusing to overwrite a capture"
        )
    # Anti-vacuous-pass guard (shared with gamry's golden_capture.snapshot):
    # an empty capture (no action output) compares to nothing and passes
    # parity trivially. Require at least one -act.yml before writing
    # anything. .hlo is NOT required in principle, but get_digital_in always
    # enqueues data on success, so its absence here is a strong signal of a
    # failed/disconnected read and is warned loudly below.
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
            f"[golden_capture_galil_io] WARNING: {len(errored)} action(s) "
            f"ERRORED and were still captured: {errored}. An errored run is "
            "NOT a valid parity baseline (it likely produced no data / "
            "partial output). Check the -act.yml error fields and the IO "
            "log before trusting a PASS."
        )
    if not hlos:
        print(
            f"[golden_capture_galil_io] WARNING: no .hlo captured under "
            f"{root} -- get_digital_in produced no data file. Parity will "
            "compare -act.yml metadata only, NOT the hlo data-write path. "
            "Verify verify_device_open passed and the galil controller is "
            "reachable."
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
        "REAL-HARDWARE get_digital_in capture (galil controller reachable "
        "at-station); NON-PERTURBING (reads a digital input only, no "
        "dev_do output is actuated). 'value' hlo values are masked via "
        "masked_hlo_columns since they are a live digital-input reading, "
        "not deterministic sim data."
    )
    if notes:
        combined_notes = f"{combined_notes} {notes}"
    ProvenanceManifest(
        scenario=SCENARIO,
        config_prefix=config_prefix,
        config_path=str(config_path),
        legacy_git_sha=sha,
        launch_cmd=f"conda run -n helao python launch.py {config_prefix} --no-hot-reload",
        sequence_name="manual_get_digital_in",
        sequence_params={
            "manual": True,
            "endpoint": "POST /IO/get_digital_in",
            "di_item": DI_ITEM,
        },
        capture_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=DIN_MASKED_HLO_COLUMNS,
        hlo_row_count_tolerance=DIN_HLO_ROW_COUNT_TOLERANCE,
        notes=combined_notes,
    ).save(out_dir)
    return out_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helao.hexagon.tests.smoke.golden_capture_galil_io",
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
    wait_for_server(IO_HOST, IO_PORT)
    verify_device_open(IO_HOST, IO_PORT)
    get_digital_in_action(args.config_prefix)
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
