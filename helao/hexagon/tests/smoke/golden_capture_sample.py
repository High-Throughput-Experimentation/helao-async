"""Runtime golden-diff capture for the sample_server hexagon canary (P3a
special-split).

*** FULLY LINUX-RUNNABLE. NO HARDWARE, NO COM/gclib, NO ORCHESTRATOR. ***

Step 0 of the parent task investigated whether ``get_loaded_positions`` needs
any hardware/backend beyond config to produce data and found: no.
``sample_server.py`` (helao/deploy/hte/servers/action/sample_server.py)
instantiates ``BaseAPI(..., driver_classes=[Archive])``, and ``Archive``
(helao/deploy/hte/drivers/data/archive_driver.py) is a pure in-memory/SQLite
sample-DB and tray/custom-position manager -- ``Archive.__init__`` opens no
hardware connection of any kind. It reads the ``positions`` config block
(``config_dict.get("positions", None)``, falling back to an empty dict when
absent) to seed ``self.startup_positions``/``self.positions``, and uses
``action_serv.helaodirs.states_root``/``db_root`` (derived purely from the
config's ``root:`` key) for its persisted ``<host>_archive.json`` state file
and the ``UnifiedSampleDataAPI`` SQLite backends
(helao/helpers/sample_api.py) -- no external DB server, no S3, no
orchestrator. This is therefore the FOURTH hardware canary in this series but
the FIRST fully-Linux-runnable one: the config's ``dummy``/``simulation`` YAML
keys are genuinely cosmetic (banner color only) here, unlike gamry/galil where
they are cosmetic despite a REAL device connection underneath -- for SAMPLE
there is no device to (not) connect to at all.

``get_loaded_positions`` (``POST /SAMPLE/get_loaded_positions``) takes NO
params and is non-perturbing (read-only): it reads ``app.driver.positions``
(the in-memory ``Positions`` built from the ``positions`` config block plus
any persisted archive state) and writes three keys into
``action.action_params``: ``_positions`` (the full archive dict),
``_tray_pos`` (loaded tray vials keyed by ``(tray, slot, vial)``), and
``_custom_pos`` (loaded custom positions keyed by name) -- see
sample_server.py's ``get_positions`` handler. With the pinned ``positions``
config (``custom: {cell1_we: cell}``, no tray config, nothing pre-loaded) and
a FRESH throwaway root (no persisted ``<host>_archive.json`` to diverge from
config), every one of these fields is deterministic and config-derived:
``_tray_pos``/``_custom_pos`` are built from a comprehension that only emits
entries for LOADED positions (``if vialbool`` / iterating ``customs_dict``,
which is empty of samples on a fresh archive), so both dicts are empty on a
fresh capture; ``_positions`` (``positions.as_dict()``) reflects only the
static tray/custom position *shape* from config, not any sample data. No
uuids/timestamps/host-identity leak into ``action_params`` for this scenario
(those are already normalized generically by ``harness.yaml_pass`` for the
-act.yml envelope fields, e.g. ``action_uuid``/``action_timestamp``). This
scenario also does NOT enqueue any ``.hlo`` data file -- ``get_positions``
only calls ``active.action.action_params.update(...)`` before ``finish()``,
never ``enqueue_data*`` -- so parity for this scenario is a metadata-only
(-act.yml) comparison, which is fine for a pure archive/DB manager. No masking
is required anywhere (``masked_hlo_columns``/``masked_meta_keys`` are both
empty below); a real hexagon-vs-legacy diff on ANY key is a genuine
regression.

Standalone counterpart to ``harness.capture.snapshot_capture`` for the
orch-less, db-less sample/samplehex 2-server topology (SAMPLE@8008 +
ACTVIS@5001 only -- no ORCH, no DB, no S3), mirroring galil's
``helao.hexagon.tests.smoke.golden_capture_galil`` (see that module's and
gamry's ``golden_capture.py``'s docstrings for the full topology-gap
rationale already recorded there). The hardware-agnostic settle/
anti-vacuous-guard logic (``settle``, ``_run_artifacts``, ``_act_status_map``)
and the production dispatch path (``dispatch_action``) are IMPORTED from
``golden_capture.py`` rather than re-implemented here. Only the
scenario-specific pieces (endpoint, masking [none], manifest notes) are new
in this module. ``golden_capture.py`` itself is NOT modified.

Usage (Linux, conda env ``helao``) -- no hardware, no pre-check needed:

    rm -rf /tmp/INST_hlo_sample_golden               (or pick a fresh --root)
    conda run -n helao python launch.py samplegold --no-hot-reload
    conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_sample \\
        --config-prefix samplegold --root /tmp/INST_hlo_sample_golden \\
        --out /tmp/golden/sample

then terminate the launch, point ``--root``/``--config-prefix`` at a FRESH
throwaway root and ``samplegoldhex``, capture again, and diff the two capture
directories with ``harness.parity``. ``sample_diff.sh`` automates exactly this
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

SAMPLE_HOST, SAMPLE_PORT = "127.0.0.1", 8008

SCENARIO = "GM-POS"

# hte canary configs (P3a/P3e relocation) live alongside this module, in
# its own configs/ sibling directory -- no longer under helao/deploy/hte/.
CONFIG_DIR = Path(__file__).resolve().parent / "configs"

# get_loaded_positions writes no .hlo data file at all (see module docstring)
# -- there is therefore nothing to mask in a data column, and no data-derived
# summary value gets written back into -act.yml action_params either (unlike
# gamry's run_OCV). Both dicts are intentionally empty: a real diff on
# _positions/_tray_pos/_custom_pos (or anything else) is a genuine
# hexagon-vs-legacy regression, never masked away.
POS_MASKED_HLO_COLUMNS: dict = {}
POS_HLO_ROW_COUNT_TOLERANCE: dict = {}
POS_ACT_YML_MASKED_META_KEYS: dict = {}


def get_loaded_positions_action(config_prefix: str) -> dict:
    """Run /SAMPLE/get_loaded_positions via ``async_action_dispatcher`` (the
    production action-dispatch path -- RPC then HTTP, full action envelope).

    No params: the endpoint always snapshots the driver's current
    ``positions`` state. Non-perturbing -- read-only, no DB/archive mutation.
    """
    return dispatch_action(config_prefix, "SAMPLE", "get_loaded_positions")


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
    # Anti-vacuous-pass guard (shared convention with gamry/galil's
    # golden_capture[_galil].snapshot): an empty capture (no action output)
    # compares to nothing and passes parity trivially. Require at least one
    # -act.yml before writing anything.
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
            f"[golden_capture_sample] WARNING: {len(errored)} action(s) "
            f"ERRORED and were still captured: {errored}. An errored run is "
            "NOT a valid parity baseline. Check the -act.yml error fields "
            "and the SAMPLE log before trusting a PASS."
        )
    # NOTE: unlike gamry/galil, a MISSING .hlo here is the EXPECTED, NORMAL
    # outcome -- get_loaded_positions never calls enqueue_data* (see module
    # docstring) -- so this is an informational note, not a WARNING. A
    # present .hlo would actually be the surprising case worth flagging.
    if hlos:
        print(
            f"[golden_capture_sample] NOTE: {len(hlos)} .hlo file(s) captured "
            f"under {root} -- unexpected for get_loaded_positions (metadata-"
            "only scenario); included in the capture regardless."
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
        "SOFTWARE-ONLY get_loaded_positions capture (Archive driver, no "
        "hardware of any kind); metadata-only (-act.yml) comparison since "
        "this scenario enqueues no .hlo data. Fully deterministic given the "
        "pinned `positions` config on a fresh root -- no masking required."
    )
    if notes:
        combined_notes = f"{combined_notes} {notes}"
    ProvenanceManifest(
        scenario=SCENARIO,
        config_prefix=config_prefix,
        config_path=str(config_path),
        legacy_git_sha=sha,
        launch_cmd=f'conda run -n helao python launch.py "{config_path}" --no-hot-reload',
        sequence_name="manual_get_loaded_positions",
        sequence_params={
            "manual": True,
            "endpoint": "POST /SAMPLE/get_loaded_positions",
        },
        capture_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=POS_MASKED_HLO_COLUMNS,
        hlo_row_count_tolerance=POS_HLO_ROW_COUNT_TOLERANCE,
        masked_meta_keys=POS_ACT_YML_MASKED_META_KEYS,
        notes=combined_notes,
    ).save(out_dir)
    return out_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helao.hexagon.tests.smoke.golden_capture_sample",
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
    wait_for_server(SAMPLE_HOST, SAMPLE_PORT)
    get_loaded_positions_action(args.config_prefix)
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
