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
import importlib
import inspect
import shutil
import subprocess
import sys
import time
import threading
from collections.abc import Callable
from dataclasses import dataclass
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

#: Which server key in a config's `servers:` block plays each capture role.
#: These three reproduce the literals above for the public `golden` config,
#: which is what makes the config-derived form a no-op for GM-1..GM-5.
DEFAULT_ROLE_KEYS: dict[str, Optional[str]] = {
    "orch": "ORCH",
    "sim": "SIM",
    "db": "SYNC",
}

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


@dataclass(frozen=True)
class Endpoint:
    """One server's host and port, as the config declares them."""

    host: str
    port: int

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True)
class CaptureEndpoints:
    """The servers a capture scenario talks to, resolved from a config.

    Ports were module constants (`ORCH 8001 / SIM 8002 / DB 8010`), which is
    fine while every scenario runs against one config and wrong the moment a
    second one exists: Deployment-C's capture config has no SIM at all and
    adds a BATCH server, and a hardcoded port silently talks to whatever else
    happens to be listening. Roles are optional by default because no config
    carries all of them.
    """

    orch: Optional[Endpoint] = None
    sim: Optional[Endpoint] = None
    db: Optional[Endpoint] = None
    batch: Optional[Endpoint] = None

    @classmethod
    def from_config(
        cls,
        config: dict,
        roles: Optional[dict[str, Optional[str]]] = None,
        optional: tuple[str, ...] = ("orch", "sim", "db", "batch"),
    ) -> "CaptureEndpoints":
        """Resolve each role to a server key in `config["servers"]`.

        `roles` overrides or extends `DEFAULT_ROLE_KEYS`; mapping a role to
        `None` declares it unused by this config (as opposed to missing from
        it). A role absent from `optional` must resolve, so a scenario that
        genuinely needs a server fails at resolution rather than at the first
        request to a port nobody is serving.
        """
        keys: dict[str, Optional[str]] = dict(DEFAULT_ROLE_KEYS)
        keys.update(roles or {})
        servers = config.get("servers", {}) or {}
        resolved: dict[str, Optional[Endpoint]] = {}
        for role, key in keys.items():
            if key is None:
                resolved[role] = None
                continue
            entry = servers.get(key)
            if entry is None:
                if role in optional:
                    resolved[role] = None
                    continue
                raise KeyError(
                    f"capture role {role!r} needs server {key!r}, "
                    f"which this config does not declare "
                    f"(has: {sorted(servers)})"
                )
            resolved[role] = Endpoint(str(entry["host"]), int(entry["port"]))
        return cls(**resolved)

    def require(self, role: str) -> Endpoint:
        endpoint = getattr(self, role, None)
        if endpoint is None:
            raise RuntimeError(
                f"this scenario needs the {role!r} endpoint, which the "
                f"capture config did not resolve"
            )
        return endpoint


def resolve_endpoints(
    config_prefix: str,
    roles: Optional[dict[str, Optional[str]]] = None,
) -> CaptureEndpoints:
    """Resolve the capture roles from a config prefix and REBIND the globals.

    The rebinding is what lets GM-1..GM-5 stay untouched: they reach the
    servers through `orch_post`/`db_post`, which read the module constants.
    Those constants are now the resolution's OUTPUT rather than its source,
    so a second capture config moves them instead of being silently ignored.
    """
    global ORCH_HOST, ORCH_PORT, SIM_HOST, SIM_PORT, DB_HOST, DB_PORT
    from helao.helpers.config_loader import read_config

    endpoints = CaptureEndpoints.from_config(read_config(config_prefix), roles)
    if endpoints.orch is not None:
        ORCH_HOST, ORCH_PORT = endpoints.orch.host, endpoints.orch.port
    if endpoints.sim is not None:
        SIM_HOST, SIM_PORT = endpoints.sim.host, endpoints.sim.port
    if endpoints.db is not None:
        DB_HOST, DB_PORT = endpoints.db.host, endpoints.db.port
    return endpoints


def endpoint_post(endpoint: Endpoint, route: str, params: Optional[dict] = None):
    r = requests.post(f"{endpoint.base_url}/{route}", params=params or {}, timeout=300)
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


# --- batch-conversion scenarios ----------------------------------------------
class UnsafeDropDirError(RuntimeError):
    """A staging target outside every root the caller declared safe.

    The batch converter RELOCATES what it converts (drop -> processing ->
    completed), so a drop directory pointed at a production share does not
    read data, it moves it. Staging refuses rather than trusting the caller.
    """


class VacuousQuiesceError(RuntimeError):
    """The quiesce predicate was never observed false.

    It therefore proves nothing: a predicate pointed at the wrong port, or at
    a submission that silently errored, is true on its first poll and the rig
    snapshots a half-written or empty tree with every other signal green.
    """


@dataclass(frozen=True)
class QuiesceObservation:
    polls: int
    observed_busy: bool
    settled: bool


def observe_quiesce(
    pred: Callable[[], bool],
    settle_polls: int = 3,
    poll_s: float = 2.0,
    timeout_s: float = 1800.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
) -> QuiesceObservation:
    """Poll `pred` until it holds `settle_polls` times in a row.

    Unlike `wait_until`, this reports HOW it settled rather than only that it
    did: `observed_busy` is the evidence the predicate can discriminate at
    all. A late false resets the run, because work that resumes after a
    quiet spell is exactly what a settle count exists to catch.
    """
    t0 = clock()
    polls = 0
    run = 0
    observed_busy = False
    while True:
        if clock() - t0 > timeout_s:
            return QuiesceObservation(polls, observed_busy, False)
        polls += 1
        if pred():
            run += 1
            if run >= settle_polls:
                return QuiesceObservation(polls, observed_busy, True)
        else:
            observed_busy = True
            run = 0
        sleep(poll_s)


def batch_quiesced(endpoints: CaptureEndpoints) -> bool:
    """All three signals the batch path can still be working through.

    Any one alone is insufficient: the watchdog reports itself idle while a
    manually-submitted conversion runs, `/list_conversions` empties the
    moment the converter hands off, and the converter POSTs its finished
    `-seq.yml` to the DB server's `/finish_yml` -- so a tree snapshotted on
    the converter's word alone is missing whatever the sync leg had not yet
    written.
    """
    batch = endpoints.require("batch")
    db = endpoints.require("db")
    status = endpoint_post(batch, "watchdog_status")
    if status.get("busy") or status.get("active_sources"):
        return False
    conversions = endpoint_post(batch, "list_conversions")
    if conversions.get("count") or conversions.get("conversions"):
        return False
    if int(endpoint_post(db, "n_queue")):
        return False
    tasks = endpoint_post(db, "tasks")
    return not tasks.get("running") and not tasks.get("num_queued")


def stage_fixture(
    fixture_dir: Path,
    drop_dir: Path,
    allowed_roots: list[Path],
) -> Path:
    """Copy a sanitized fixture into a drop folder, refusing unsafe targets.

    Copy, never move: the fixtures are checked-in inputs every later slice
    replays, and the converter consumes what it is given.
    """
    fixture_dir = Path(fixture_dir)
    drop_dir = Path(drop_dir)
    resolved = drop_dir.resolve()
    roots = [Path(r).resolve() for r in allowed_roots]
    if not any(resolved == r or resolved.is_relative_to(r) for r in roots):
        raise UnsafeDropDirError(
            f"refusing to stage into {drop_dir} -- outside every allowed root "
            f"({[str(r) for r in roots]}). The converter RELOCATES sources."
        )
    staged = drop_dir / fixture_dir.name
    if staged.exists():
        raise FileExistsError(
            f"{staged} already exists; a capture stages into a fresh tree so "
            f"a rerun cannot inherit a previous run's half-moved sources"
        )
    drop_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture_dir, staged)
    return staged


def make_batch_scenario(
    family: str,
    fixture_dir: Path,
    drop_dir: Path,
    poll_s: float = 2.0,
    settle_polls: int = 3,
    timeout_s: float = 1800.0,
    require_observed_busy: bool = True,
    allowed_roots: Optional[list[Path]] = None,
) -> Callable[[Path, CaptureEndpoints], tuple[str, dict]]:
    """Build the driver for one conversion family.

    Submission is `/run_directory` on the staged path, never the filesystem
    watchdog: the watchdog decides a folder is ready by a settle heuristic
    over mtimes and sizes, which makes both WHEN a capture starts and WHETHER
    it starts at all depend on the host's timing.
    """

    def driver(root: Path, endpoints: CaptureEndpoints) -> tuple[str, dict]:
        batch = endpoints.require("batch")
        endpoints.require("db")
        staged = stage_fixture(
            Path(fixture_dir), Path(drop_dir), allowed_roots or [Path(root)]
        )

        result: dict = {}

        def _submit() -> None:
            result["body"] = endpoint_post(
                batch, "run_directory", params={"source_dir": str(staged)}
            )

        thread = threading.Thread(target=_submit, daemon=True)
        thread.start()
        # Arm the observation: poll until the conversion is visibly in flight
        # or the request has already returned. Without this the settle run can
        # complete on polls taken before the server ever saw the request, and
        # a genuinely slow conversion would be recorded as vacuous.
        while thread.is_alive() and batch_quiesced(endpoints):
            time.sleep(poll_s)
        observation = observe_quiesce(
            lambda: batch_quiesced(endpoints),
            settle_polls=settle_polls,
            poll_s=poll_s,
            timeout_s=timeout_s,
        )
        thread.join(timeout=timeout_s)
        if thread.is_alive():
            raise TimeoutError(f"/run_directory for {family} never returned")
        if not observation.settled:
            raise TimeoutError(
                f"batch quiesce for {family} not reached in {timeout_s}s"
            )

        body = result.get("body") or {}
        if body.get("error"):
            raise RuntimeError(f"/run_directory failed: {body['error']}")
        results = body.get("results") or {}
        empty = [src for src, uuid in results.items() if not uuid]
        if empty or not results:
            raise RuntimeError(
                f"{family}: {empty or [str(staged)]} produced no sequence "
                f"(the converter returned no uuid, so there is nothing to "
                f"snapshot and a diff against it would compare two nothings)"
            )
        if require_observed_busy and not observation.observed_busy:
            raise VacuousQuiesceError(
                f"batch quiesce for {family} was never observed false: the "
                f"predicate settled on its first polls, so it discriminates "
                f"nothing. Check the endpoints resolve to the running servers."
            )
        return f"batch__{family}", {
            "family": family,
            "fixture": str(fixture_dir),
            "staged": str(staged),
            "instrument": body.get("instrument"),
            "source": body.get("source"),
            "results": results,
            "quiesce_polls": observation.polls,
            "quiesce_observed_busy": observation.observed_busy,
        }

    return driver


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


def load_scenario_module(dotted: str) -> tuple[dict, dict, dict]:
    """Import a deployment's scenario table.

    A deployment's scenarios name its own instrument families, drop-tree
    layout and fixture paths — none of which belong in this repo, which is a
    public remote. So the generic machinery lives here and the table lives
    beside the deployment it describes, exposing:

        SCENARIOS       {name: driver(root, endpoints) -> (seq_name, params)}
        SCENARIO_MASKS  {name: (masked_hlo, tolerance, content_masked)}
        ROLE_KEYS       {role: server key}   (optional; e.g. a BATCH server)

    Names must not collide with the built-ins; a collision is an error rather
    than a silent shadow, because the built-in would keep running under the
    name the caller thought they were overriding.
    """
    module = importlib.import_module(dotted)
    scenarios = dict(getattr(module, "SCENARIOS", {}))
    masks = dict(getattr(module, "SCENARIO_MASKS", {}))
    roles = dict(getattr(module, "ROLE_KEYS", {}))
    if not scenarios:
        raise RuntimeError(f"{dotted} defines no SCENARIOS")
    clash = sorted(set(scenarios) & set(SCENARIOS))
    if clash:
        raise RuntimeError(f"{dotted} redefines built-in scenarios: {clash}")
    missing = sorted(set(scenarios) - set(masks))
    if missing:
        raise RuntimeError(f"{dotted} declares no SCENARIO_MASKS for: {missing}")
    return scenarios, masks, roles


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m harness.capture", description=__doc__
    )
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config-prefix", default="golden")
    parser.add_argument(
        "--scenarios",
        default="",
        help="dotted module supplying a deployment's SCENARIOS/SCENARIO_MASKS",
    )
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    scenarios: dict = dict(SCENARIOS)
    masks: dict = dict(SCENARIO_MASKS)
    roles: dict = {}
    if args.scenarios:
        extra, extra_masks, roles = load_scenario_module(args.scenarios)
        scenarios.update(extra)
        masks.update(extra_masks)
    if args.scenario not in scenarios:
        parser.error(
            f"unknown scenario {args.scenario!r}; available: {sorted(scenarios)}"
            + ("" if args.scenarios else " (pass --scenarios to add a deployment's)")
        )

    assert_fresh(args.root)
    # Roles come from the scenario module, so a deployment whose capture config
    # has no SIM (or an extra BATCH) resolves what it actually declares rather
    # than what the public golden config happens to.
    endpoints = resolve_endpoints(args.config_prefix, roles or None)
    for role in ("orch", "sim", "db", "batch"):
        endpoint = getattr(endpoints, role)
        if endpoint is not None:
            wait_for_server(endpoint.host, endpoint.port)
    driver = scenarios[args.scenario]
    # Built-in scenarios predate config-derived endpoints and take the root
    # alone; deployment scenarios take both. Dispatch on the signature rather
    # than on a naming convention, which would break the first time someone
    # names one differently.
    if len(inspect.signature(driver).parameters) >= 2:
        seq_name, seq_params = driver(args.root, endpoints)
    else:
        seq_name, seq_params = driver(args.root)
    masked, tolerance, content_masked = masks[args.scenario]
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
