"""Golden-master capture rig (spec §6.2): submit, quiesce, snapshot, manifest.

The rig NEVER launches or kills servers. Launch the group first, in another
terminal, from the repo root:

    rm -rf /home/dan/INST_hlo_golden          # captures start from a FRESH root
    conda run -n helao python launch.py golden --no-hot-reload

then run one scenario:

    conda run -n helao python -m harness.capture --scenario GM-1 \
        --root /home/dan/INST_hlo_golden \
        --out /home/dan/helao_goldens/GM-1/run1

and CTRL-x the launch terminal afterwards. One scenario per launch: the rig
refuses a root that already contains run artifacts, so re-launch (with a
fresh root) between scenarios and between the run1/run2 baseline captures.

Determinism levers (spec §6.1): fixed wait_time/data_duration; GM-4 uses
wait_time=20.0 so 5 s-in control POSTs always land inside action 0; WsSim
random values are masked via the manifest column lists; quiesce-before-
snapshot per §5.7 (orch stopped + DB queue drained + RUNS_ACTIVE settled,
three consecutive clean polls).
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Optional

import requests

from harness import HARNESS_VERSION
from harness.manifest import ProvenanceManifest
from harness.treepass import PARITY_TOPS
from helao.core.error import ErrorCodes
from helao.helpers.dispatcher import private_dispatcher
from helao.helpers.premodels import ExperimentPlanMaker, Sequence
from helao.helpers.time_utils import gen_uuid

ORCH_HOST, ORCH_PORT = "127.0.0.1", 8001
SIM_HOST, SIM_PORT = "127.0.0.1", 8002
DB_HOST, DB_PORT = "127.0.0.1", 8010

# WsExec streams epoch_s + series_0..5 (ws_simulator.py); values are unseeded
# np.random -> masked per §5.5 "unseeded sim data values", counts compared
# within a small poll-jitter tolerance recorded here (manifest-resident, §6.4).
WSSIM_COLUMNS = [
    "epoch_s",
    "series_0",
    "series_1",
    "series_2",
    "series_3",
    "series_4",
    "series_5",
]
WSSIM_MASKED = {
    "*WsSim*.hlo": WSSIM_COLUMNS,
    "*WsSim*.hlo.json*": WSSIM_COLUMNS,
}
WSSIM_TOLERANCE = {"*WsSim*.hlo": 3, "*WsSim*.hlo.json*": 3}
# hlo_to_csv output derives from the masked random columns: line-count only.
WSSIM_CONTENT_MASKED = {"*.csv": "line-count"}


# --- wire helpers -----------------------------------------------------------
def wait_for_server(host: str, port: int, timeout_s: float = 180.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            r = requests.post(f"http://{host}:{port}/get_status", timeout=2)
            if r.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise TimeoutError(f"server {host}:{port} not up after {timeout_s}s")


def orch_post(
    endpoint: str, params: Optional[dict] = None, body: Optional[dict] = None
):
    resp, err = private_dispatcher(
        "ORCH",
        ORCH_HOST,
        ORCH_PORT,
        endpoint,
        params_dict=params or {},
        json_dict=body or {},
    )
    if err != ErrorCodes.none:
        raise RuntimeError(f"ORCH /{endpoint} failed: {err}")
    return resp


def db_post(endpoint: str, params: Optional[dict] = None):
    r = requests.post(
        f"http://{DB_HOST}:{DB_PORT}/{endpoint}", params=params or {}, timeout=30
    )
    r.raise_for_status()
    return r.json()


def submit_and_start(seq: Sequence) -> None:
    orch_post("append_sequence", body={"sequence": seq.as_dict()})
    orch_post("start")


def loop_state() -> tuple[str, bool]:
    gs = requests.post(
        f"http://{ORCH_HOST}:{ORCH_PORT}/global_status", timeout=10
    ).json()
    return str(gs.get("loop_state")), bool(gs.get("active_dict"))


def orch_stopped() -> bool:
    state, active = loop_state()
    return state.endswith("stopped") and not active


def db_drained() -> bool:
    n = db_post("n_queue")
    tasks = db_post("tasks")
    return n == 0 and not tasks.get("running")


def runs_active_empty(root: Path) -> bool:
    active = Path(root) / "RUNS_ACTIVE"
    if not active.is_dir():
        return True
    return next(active.rglob("*.yml"), None) is None


def wait_until(pred: Callable[[], bool], timeout_s: float = 600.0, poll_s: float = 2.0):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if pred():
            return
        time.sleep(poll_s)
    raise TimeoutError(f"condition {pred.__name__} not met after {timeout_s}s")


def quiesce(
    root: Path,
    require_orch: bool = True,
    require_active_empty: bool = True,
    settle_polls: int = 3,
    poll_s: float = 2.0,
    timeout_s: float = 1800.0,
) -> None:
    """§5.7 quiesce: fire-and-forget moves settled before snapshotting."""
    t0 = time.time()
    settled = 0
    while time.time() - t0 < timeout_s:
        ok = db_drained()
        if require_orch:
            ok = ok and orch_stopped()
        if require_active_empty:
            ok = ok and runs_active_empty(root)
        settled = settled + 1 if ok else 0
        if settled >= settle_polls:
            return
        time.sleep(poll_s)
    raise TimeoutError("group did not quiesce")


# --- scenario builders ------------------------------------------------------
def build_gm1_sequence() -> Sequence:
    epm = ExperimentPlanMaker()
    epm.add("SIM_websocket_data", {"wait_time": 2.0, "data_duration": 4.0})
    epm.add("SIM_websocket_data", {"wait_time": 2.0, "data_duration": 4.0})
    return Sequence(
        sequence_name="SIM_websocket_data_seq",
        sequence_label="golden",
        sequence_params={"wait_time": 2.0, "data_duration": 4.0},
        planned_experiments=epm.planned_experiments,
        sequence_uuid=gen_uuid(),
        dummy=True,
        simulation=True,
    )


GM2_PARAMS = {"wait_time": 2.0, "cycles": 2, "plate_sample_no_list": [1, 2]}


def build_gm2_sequence() -> Sequence:
    from helao.deploy.test.sequences.TEST_seq import TEST_consecutive_noblocking

    return Sequence(
        sequence_name="TEST_consecutive_noblocking",
        sequence_label="golden",
        sequence_params=GM2_PARAMS,
        planned_experiments=TEST_consecutive_noblocking(**GM2_PARAMS),
        sequence_uuid=gen_uuid(),
        dummy=True,
        simulation=True,
    )


def build_gm4_sequence(label: str) -> Sequence:
    epm = ExperimentPlanMaker()
    epm.add("SIM_websocket_data", {"wait_time": 20.0, "data_duration": 4.0})
    epm.add("SIM_websocket_data", {"wait_time": 20.0, "data_duration": 4.0})
    return Sequence(
        sequence_name="SIM_websocket_data_seq",
        sequence_label=label,
        sequence_params={"wait_time": 20.0, "data_duration": 4.0},
        planned_experiments=epm.planned_experiments,
        sequence_uuid=gen_uuid(),
        dummy=True,
        simulation=True,
    )


# --- scenario drivers (return sequence_name, sequence_params for provenance) -
def run_gm1(root: Path) -> tuple[str, dict]:
    seq = build_gm1_sequence()
    submit_and_start(seq)
    quiesce(root)
    return str(seq.sequence_name), dict(seq.sequence_params)


def run_gm2(root: Path) -> tuple[str, dict]:
    seq = build_gm2_sequence()
    submit_and_start(seq)
    quiesce(root)
    return str(seq.sequence_name), dict(seq.sequence_params)


def run_gm3(root: Path) -> tuple[str, dict]:
    """Manual action: direct POST bypasses the orch (RUNS_DIAG tree)."""
    r = requests.post(
        f"http://{SIM_HOST}:{SIM_PORT}/SIM/acquire_data",
        params={"duration": 2.0, "acquisition_rate": 0.2},
        json={"fast_samples_in": []},
        timeout=60,
    )
    r.raise_for_status()
    # manual runs never touch the syncer; settle on RUNS_ACTIVE emptying only
    quiesce(root, require_orch=False)
    return "", {"duration": 2.0, "acquisition_rate": 0.2, "manual": True}


def run_gm4(root: Path) -> tuple[str, dict]:
    # Leg 1 — stop-intent drain, then resume to completion.
    submit_and_start(build_gm4_sequence("GM4_stop"))
    time.sleep(5)  # inside experiment 1's first 20 s wait
    orch_post("stop")
    wait_until(orch_stopped, timeout_s=600)
    orch_post("start")  # resume: remaining experiment runs to completion
    quiesce(root)
    # Leg 2 — skip_experiment clears action_dq; running wait completes,
    # remaining actions of experiment 1 are dropped, experiment 2 runs fully.
    submit_and_start(build_gm4_sequence("GM4_skip"))
    time.sleep(5)
    orch_post("skip_experiment")
    quiesce(root)
    # Leg 3 — estop mid-experiment: [finished, estopped] artifacts, deferred
    # promotion (§5.4 items 5-6); wait past the 30 s child-dir window.
    submit_and_start(build_gm4_sequence("GM4_estop"))
    time.sleep(5)
    orch_post("estop_orch")
    wait_until(lambda: loop_state()[0].endswith("estopped"), timeout_s=300)
    time.sleep(40)
    quiesce(root, require_orch=False, require_active_empty=False)
    orch_post("clear_estop")
    return "SIM_websocket_data_seq", {
        "wait_time": 20.0,
        "data_duration": 4.0,
        "legs": ["stop+resume", "skip", "estop"],
    }


def run_gm5(root: Path) -> tuple[str, dict]:
    """GM-1 through the sync leg + reset_sync/finish_pending round-trip."""
    seq = build_gm1_sequence()
    submit_and_start(seq)
    quiesce(root)
    zips = sorted((Path(root) / "RUNS_SYNCED").rglob("*.zip"))
    if not zips:
        raise RuntimeError("GM-5: no RUNS_SYNCED zip after quiesce")
    db_post("reset_sync", params={"sync_path": str(zips[0])})
    db_post("finish_pending", params={"actions_first": True})
    quiesce(root)
    if not sorted((Path(root) / "RUNS_SYNCED").rglob("*.zip")):
        raise RuntimeError("GM-5: re-sync did not restore the RUNS_SYNCED zip")
    return str(seq.sequence_name), dict(
        seq.sequence_params, round_trip="reset_sync+finish_pending"
    )


SCENARIOS: dict[str, Callable[[Path], tuple[str, dict]]] = {
    "GM-1": run_gm1,
    "GM-2": run_gm2,
    "GM-3": run_gm3,
    "GM-4": run_gm4,
    "GM-5": run_gm5,
}

SCENARIO_MASKS: dict[str, tuple] = {
    # (masked_hlo_columns, hlo_row_count_tolerance, content_masked_files)
    "GM-1": (WSSIM_MASKED, WSSIM_TOLERANCE, WSSIM_CONTENT_MASKED),
    "GM-2": ({}, {}, {}),
    "GM-3": (WSSIM_MASKED, WSSIM_TOLERANCE, WSSIM_CONTENT_MASKED),
    "GM-4": (WSSIM_MASKED, WSSIM_TOLERANCE, WSSIM_CONTENT_MASKED),
    "GM-5": (WSSIM_MASKED, WSSIM_TOLERANCE, WSSIM_CONTENT_MASKED),
}


# --- snapshot ----------------------------------------------------------------
def assert_fresh(root: Path) -> None:
    finished = Path(root) / "RUNS_FINISHED"
    if finished.is_dir() and next(finished.rglob("*.yml"), None) is not None:
        raise RuntimeError(
            f"{root} already contains run artifacts; captures require a fresh "
            "root (rm -rf it, then re-launch)"
        )
    synced = Path(root) / "RUNS_SYNCED"
    if synced.is_dir() and next(synced.rglob("*"), None) is not None:
        raise RuntimeError(f"{root}/RUNS_SYNCED is not empty; use a fresh root")


def snapshot_capture(
    root: Path,
    out_dir: Path,
    scenario: str,
    config_prefix: str,
    sequence_name: str,
    sequence_params: dict,
    masked_hlo: dict,
    tolerance: dict,
    content_masked: dict,
    notes: str = "",
) -> Path:
    root, out_dir = Path(root), Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(
            f"{out_dir} already exists; refusing to overwrite a capture"
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
    config_path = (
        Path(__file__).resolve().parents[1]
        / "helao"
        / "deploy"
        / "test"
        / "configs"
        / f"{config_prefix}.yml"
    )
    ProvenanceManifest(
        scenario=scenario,
        config_prefix=config_prefix,
        config_path=str(config_path),
        legacy_git_sha=sha,
        launch_cmd=f"conda run -n helao python launch.py {config_prefix} --no-hot-reload",
        sequence_name=sequence_name,
        sequence_params=sequence_params,
        capture_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=masked_hlo,
        hlo_row_count_tolerance=tolerance,
        content_masked_files=content_masked,
        notes=notes,
    ).save(out_dir)
    return out_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m harness.capture", description=__doc__
    )
    parser.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config-prefix", default="golden")
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)
    assert_fresh(args.root)
    wait_for_server(ORCH_HOST, ORCH_PORT)
    wait_for_server(SIM_HOST, SIM_PORT)
    wait_for_server(DB_HOST, DB_PORT)
    seq_name, seq_params = SCENARIOS[args.scenario](args.root)
    masked, tolerance, content_masked = SCENARIO_MASKS[args.scenario]
    out = snapshot_capture(
        root=args.root,
        out_dir=args.out,
        scenario=args.scenario,
        config_prefix=args.config_prefix,
        sequence_name=seq_name,
        sequence_params=seq_params,
        masked_hlo=masked,
        tolerance=tolerance,
        content_masked=content_masked,
        notes=args.notes,
    )
    print(f"captured {args.scenario} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
