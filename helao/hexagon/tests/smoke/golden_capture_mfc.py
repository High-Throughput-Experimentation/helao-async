"""Runtime golden-diff capture for the mfc_server hexagon canary (P3a
special-split).

*** DRIVES THE REAL ALICAT MASS FLOW CONTROLLER (READ-ONLY, NON-PERTURBING). ***

Like gamry/galil (and unlike sample), mfc_server has NO sim/dummy data path:
``AliCatMFC.connect`` (helao/deploy/hte/drivers/mfc/alicat_driver.py) opens a
real ``FlowController`` on the configured serial COM port and ``mfc_server.py``
instantiates ``driver_classes=[AliCatMFC]`` unconditionally -- the config's
``dummy``/``simulation`` YAML keys are cosmetic (banner color) for this canary
only. (One difference from gamry: ``AliCatMFC.__init__`` does NO device I/O and
``connect()`` exceptions are caught, so the server still BOOTS + serves
/openapi.json with no MFC attached -- that is what the openapi mfc_canary.bat
relies on. This RUNTIME capture, however, needs the live device: with no Alicat
on COM4 the poller buffers nothing and ``MfcExec._poll`` errors reading an empty
live buffer.) So this capture rig is an AT-STATION, REAL-HARDWARE gate: the
Alicat MFC must be attached on COM4 for ``acquire_flowrate`` to produce data.

SAFETY -- why acquire_flowrate is the non-perturbing choice
-----------------------------------------------------------
``acquire_flowrate`` (``POST /MFC/acquire_flowrate``) is dispatched here with
``flowrate_sccm`` LEFT UNSET (defaults to ``None``). Under that default the
``MfcExec`` executor:
  * ``_pre_exec``: ``if flowrate_sccm is not None`` -> SKIPPED. No ``set_flowrate``
    is issued (no setpoint written, no flow commanded).
  * ``_exec``:     ``if flowrate_sccm is not None`` -> SKIPPED. No ``hold_cancel``
    is issued (the valve is NEVER opened).
  * ``_poll``:     reads the live status buffer only (pressure/temperature/
    flow/setpoint/gas/...); it drives nothing.
  * ``_post_exec``: unless ``stay_open`` (left False here), ``hold_valve_closed``
    forces the setpoint to 0 and latches the valve CLOSED -- i.e. it ends in the
    SAFEST state (no gas flow), not a perturbed one.
So the action never opens the valve or commands flow: it streams telemetry and
finishes with the valve closed. The set_flowrate/set_pressure/maintain_*/
hold_valve_* endpoints (which actively drive gas/valves) and the cancel_*
endpoints are deliberately NOT exercised.

A SHORT finite ``duration`` (default 2.0s) is passed so the streamed action
reaches a TERMINAL ``action_status`` and writes its ``-act.yml``; the default
``duration=-1`` would run until cancelled and never settle.

Masking
-------
``acquire_flowrate`` streams the per-poll live-buffer dict as the ``.hlo`` body:
``epoch_s``, ``acquire_time``, ``pressure``, ``temperature``, ``volumetric_flow``,
``mass_flow``, ``setpoint`` (and ``total flow`` on totalizer units) are live
sensor/clock readings, non-deterministic run-to-run, so their VALUES are masked
via the manifest's ``masked_hlo_columns``. The categorical/config-deterministic
columns ``gas`` and ``control_point`` are NOT masked (they are the deterministic
anchors -- the .hlo analogue of spec's ``wl`` header -- and a diff there is a
real regression). The stream is POLL-PACED (~``duration``/``acquisition_rate``
rows), so row counts jitter a row or two run-to-run and are compared within
``hlo_row_count_tolerance`` (not exact).

Unlike gamry's ``run_OCV`` (which stashes several summaries), ``MfcExec._post_exec``
writes exactly ONE data-derived value back into ``action_params``:
``total_scc`` (the integral of the live flow reading). It is masked via the
manifest's ``masked_meta_keys`` so ``-act.yml`` parity is a clean PASS when only
that integrated value differs, while a diff in any other key still surfaces.

Standalone counterpart to ``harness.capture.snapshot_capture`` for the
orch-less, db-less mfc/mfchex 2-server topology (MFC@8009 + ACTVIS@5001 only --
no ORCH, no DB), mirroring gamry/galil/spec's ``golden_capture[_spec].py`` (see
those modules' docstrings for the full topology-gap rationale). The
hardware-agnostic settle / anti-vacuous-guard logic (``settle``,
``_run_artifacts``, ``_act_status_map``) and the production dispatch path
(``dispatch_action``) are IMPORTED from ``golden_capture.py`` rather than
re-implemented here; only the scenario-specific pieces (endpoint, masking,
manifest notes) are new. ``golden_capture.py`` itself is NOT modified.

Usage (AT-STATION, Windows, conda env ``helao``) -- ATTACH THE ALICAT MFC FIRST:

    rmdir /s /q C:\\INST_hlo_golden               (or pick a fresh --root)
    conda run -n helao python launch.py mfcgold --no-hot-reload
    conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_mfc ^
        --config-prefix mfcgold --root C:\\INST_hlo_golden ^
        --out C:\\golden\\mfc

then terminate the launch, point ``--root``/``--config-prefix`` at a FRESH
throwaway root and ``mfcgoldhex``, capture again, and diff the two capture
directories with ``harness.parity``. ``mfc_diff.bat`` automates exactly this
sequence.
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import subprocess
import sys
from pathlib import Path

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

MFC_HOST, MFC_PORT = "127.0.0.1", 8009

SCENARIO = "GM-MFCFLOW"

# helao/hexagon/tests/smoke/golden_capture_mfc.py -> repo root is 4 parents up
# (matches safe_root.py's own _repo_root()).
REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = REPO_ROOT / "helao" / "deploy" / "hte" / "configs"

# The single MFC device declared in the mfc*.yml MFC block (ccsi1.yml verbatim:
# devices: {CO2: {port: COM4, unit_id: A}}). devices[0] == "CO2" is the endpoint
# default for device_name; passed explicitly here so both captures target the
# same controller deterministically.
DEVICE_NAME = "CO2"

# acquire_flowrate (MfcExec._poll) streams the per-poll live-buffer status dict
# (helao/deploy/hte/drivers/mfc/alicat_driver.py: FlowController.get_status +
# the executor's added epoch_s) as the .hlo body. These columns are live
# sensor/clock readings pulled straight off the Alicat -- no seeded/
# deterministic sim values exist in this driver -- so their VALUES are masked
# for parity. "total flow" is present only on totalizer-equipped units; masking
# it is a harmless no-op otherwise. The categorical config-deterministic columns
# (gas, control_point) are intentionally NOT masked (the deterministic anchors).
MFC_HLO_COLUMNS = [
    "epoch_s",
    "acquire_time",
    "pressure",
    "temperature",
    "volumetric_flow",
    "mass_flow",
    "setpoint",
    "total flow",
]
MFC_MASKED_HLO_COLUMNS = {
    "*.hlo": MFC_HLO_COLUMNS,
    "*.hlo.json*": MFC_HLO_COLUMNS,
}
# acquire_flowrate is a POLL-PACED stream (~duration/acquisition_rate rows), so
# the row count jitters a row or two run-to-run (poll timing) -- compare masked
# columns within a small tolerance, not exactly (mirrors gamry run_OCV).
MFC_HLO_ROW_COUNT_TOLERANCE = {"*.hlo": 2, "*.hlo.json*": 2}
# MfcExec._post_exec writes exactly one data-derived summary back into
# action_params: total_scc (integral of the live flow). It derives from the same
# masked live measurement and is not covered by masked_hlo_columns (.hlo only)
# nor by normalize_meta's §5.5 volatile lists (it is a plain float leaf under
# action_params). Mask its VALUE via masked_meta_keys so -act.yml parity is a
# clean PASS when only it differs; presence + every other key still diff normally.
MFC_ACT_YML_MASKED_META_KEYS = {
    "*-act.yml": ["action_params.total_scc"],
}


def acquire_flowrate_action(
    config_prefix: str,
    device_name: str = DEVICE_NAME,
    duration: float = 2.0,
    acquisition_rate: float = 0.2,
) -> dict:
    """Run /MFC/acquire_flowrate via ``async_action_dispatcher`` (production
    action-dispatch path -- RPC then HTTP, full action envelope).

    ``flowrate_sccm`` is deliberately OMITTED (defaults to ``None``): under that
    default ``MfcExec`` never issues ``set_flowrate`` and never opens the valve
    -- it only READS live telemetry, then (``stay_open`` False) latches the valve
    CLOSED at the end. ``duration`` is a SHORT finite value so the streamed
    action settles to a terminal status (the default ``-1`` runs until cancelled).
    """
    return dispatch_action(
        config_prefix,
        "MFC",
        "acquire_flowrate",
        {
            "device_name": device_name,
            "duration": duration,
            "acquisition_rate": acquisition_rate,
        },
        # short stream, but leave headroom for the endpoint's trailing
        # dangling-data drain + finish().
        timeout=60,
    )


def snapshot(
    root: Path,
    out_dir: Path,
    config_prefix: str,
    device_name: str,
    duration: float,
    acquisition_rate: float,
    notes: str = "",
) -> Path:
    """Copy PARITY_TOPS from ``root`` and write a provenance manifest.

    Refuses to overwrite an existing ``out_dir``, matching
    ``harness.capture.snapshot_capture`` / gamry/spec's ``golden_capture.snapshot``.
    """
    root, out_dir = Path(root), Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(
            f"{out_dir} already exists; refusing to overwrite a capture"
        )
    # Anti-vacuous-pass guard (shared convention with gamry/galil/spec/sample):
    # an empty capture (no action output) compares to nothing and passes parity
    # trivially. Require at least one -act.yml before writing anything.
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
            f"[golden_capture_mfc] WARNING: {len(errored)} action(s) ERRORED "
            f"and were still captured: {errored}. An errored run is NOT a valid "
            "parity baseline. Check the -act.yml error fields and the MFC log "
            "before trusting a PASS (e.g. no Alicat on COM4 -> empty live buffer)."
        )
    if not hlos:
        print(
            f"[golden_capture_mfc] WARNING: no .hlo captured under {root} -- "
            "acquire_flowrate produced no telemetry data file. Parity will "
            "compare -act.yml metadata only, NOT the hlo data-write path. Verify "
            "the Alicat MFC is attached on COM4 and the poller is buffering data."
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
        "REAL-HARDWARE acquire_flowrate capture (Alicat MFC attached on COM4); "
        "NOT a simulation -- AliCatMFC has no sim/dummy data path. Dispatched "
        "with flowrate_sccm=None so the MFC valve is NEVER opened and NO flow is "
        "commanded (pure telemetry read; ends valve-closed). The .hlo body "
        "columns epoch_s/acquire_time/pressure/temperature/volumetric_flow/"
        "mass_flow/setpoint (+ total flow) are live device readings, masked via "
        "masked_hlo_columns; gas/control_point are config-deterministic and "
        "compared unmasked. action_params.total_scc (integrated live flow) is "
        "masked via masked_meta_keys. Row counts are poll-paced -> compared "
        "within hlo_row_count_tolerance."
    )
    if notes:
        combined_notes = f"{combined_notes} {notes}"
    ProvenanceManifest(
        scenario=SCENARIO,
        config_prefix=config_prefix,
        config_path=str(config_path),
        legacy_git_sha=sha,
        launch_cmd=f"conda run -n helao python launch.py {config_prefix} --no-hot-reload",
        sequence_name="manual_acquire_flowrate",
        sequence_params={
            "manual": True,
            "endpoint": "POST /MFC/acquire_flowrate",
            "device_name": device_name,
            "flowrate_sccm": None,
            "duration": duration,
            "acquisition_rate": acquisition_rate,
            "fast_samples_in": [],
        },
        capture_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=MFC_MASKED_HLO_COLUMNS,
        hlo_row_count_tolerance=MFC_HLO_ROW_COUNT_TOLERANCE,
        masked_meta_keys=MFC_ACT_YML_MASKED_META_KEYS,
        notes=combined_notes,
    ).save(out_dir)
    return out_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helao.hexagon.tests.smoke.golden_capture_mfc",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config-prefix", required=True)
    parser.add_argument(
        "--device-name",
        default=DEVICE_NAME,
        help=f"MFC device_name (default {DEVICE_NAME})",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=2.0,
        help="acquire_flowrate duration in seconds; SHORT + finite so the "
        "stream settles (default 2.0). flowrate_sccm stays None (safe read).",
    )
    parser.add_argument(
        "--acquisition-rate",
        type=float,
        default=0.2,
        help="executor poll period in seconds (default 0.2)",
    )
    parser.add_argument("--settle-polls", type=int, default=3)
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    assert_fresh(args.root)
    wait_for_server(MFC_HOST, MFC_PORT)
    acquire_flowrate_action(
        args.config_prefix,
        device_name=args.device_name,
        duration=args.duration,
        acquisition_rate=args.acquisition_rate,
    )
    settle(args.root, settle_polls=args.settle_polls)
    out = snapshot(
        root=args.root,
        out_dir=args.out,
        config_prefix=args.config_prefix,
        device_name=args.device_name,
        duration=args.duration,
        acquisition_rate=args.acquisition_rate,
        notes=args.notes,
    )
    print(f"captured {SCENARIO} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
