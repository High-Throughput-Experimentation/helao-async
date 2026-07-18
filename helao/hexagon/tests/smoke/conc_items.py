"""§10.3 launched-group concurrency drivers (items 2/4/6/7, P1b2b).

Runs against a LIVE launched group (launch.py <prefix>) — MAIN SESSION only
(background subagent launches get reaped on idle). Invoked by conc_run.sh.
Exit code: 0 PASS, 1 assertion failure, 2 driver error.

Item drivers are registered in ITEMS:
  item2 (non-default identity), item4 (serial >=3 experiments),
  item6 (history-poll hang exit), item7 (idle drain + non-blank history)."""

import argparse
import pickle
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

import psutil
import requests

from helao.core.error import ErrorCodes
from helao.helpers.dispatcher import private_dispatcher
from helao.helpers.premodels import ExperimentPlanMaker, Sequence
from helao.helpers.time_utils import gen_uuid

ORCH_HOST, ORCH_PORT = "127.0.0.1", 8001
HIST_TS_FMT = "%m-%d %H:%M:%S"  # orch action_history timestamp format


def orch_post(
    orch_key: str,
    endpoint: str,
    params: Optional[dict] = None,
    body: Optional[dict] = None,
):
    resp, err = private_dispatcher(
        orch_key,
        ORCH_HOST,
        ORCH_PORT,
        endpoint,
        params_dict=params or {},
        json_dict=body or {},
    )
    if err != ErrorCodes.none:
        raise RuntimeError(f"{orch_key} /{endpoint} failed: {err}")
    return resp


def get_orch_state(orch_key: str) -> dict:
    return orch_post(orch_key, "get_orch_state")


def get_histories(orch_key: str) -> dict:
    return orch_post(orch_key, "get_histories")


def orch_parked(orch_key: str) -> bool:
    st = get_orch_state(orch_key)
    loop = str(st.get("loop_state"))
    return loop.endswith("stopped") and not st.get("active_experiment")


def wait_until(
    pred: Callable[[], bool], timeout_s: float, poll_s: float = 2.0, label: str = ""
):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if pred():
            return
        time.sleep(poll_s)
    raise TimeoutError(f"{label or pred.__name__} not met after {timeout_s}s")


def build_ws_sequence(
    n_exps: int, wait_time: float = 2.0, data_duration: float = 4.0
) -> Sequence:
    epm = ExperimentPlanMaker()
    for _ in range(n_exps):
        epm.add(
            "SIM_websocket_data",
            {"wait_time": wait_time, "data_duration": data_duration},
        )
    return Sequence(
        sequence_name="SIM_websocket_data_seq",
        sequence_label="p1b2b-conc",
        sequence_params={"wait_time": wait_time, "data_duration": data_duration},
        planned_experiments=epm.planned_experiments,
        sequence_uuid=gen_uuid(),
        dummy=True,
        simulation=True,
    )


def submit_and_start(orch_key: str, seq: Sequence) -> None:
    orch_post(orch_key, "append_sequence", body={"sequence": seq.as_dict()})
    orch_post(orch_key, "start")


def kill_server(root: Path, prefix: str, key: str) -> None:
    """SIGKILL one server of the launched group (models a hard death)."""
    pck = root / "STATES" / f"pids_{prefix}_.pck"
    pidd = pickle.load(open(pck, "rb"))
    pid = pidd[key]["pid"]
    print(f"[conc] SIGKILL {key} (pid {pid})")
    psutil.Process(pid).kill()


def parse_hist_ts(s: str) -> datetime:
    return datetime.strptime(s.strip(), HIST_TS_FMT)


ITEMS: Dict[str, Callable[[Path, str, str], int]] = {}
# Registered below: ITEMS["item2"], ITEMS["item4"], ITEMS["item6"], ITEMS["item7"]
# Signature: (root, orch_key, prefix) -> rc


def item2_nondefault_identity(root: Path, orch_key: str, prefix: str) -> int:
    """§10.3 item 2: full run under a non-default orch MachineModel
    (HEXORC). MINOR-8 regression mode = permanent stall (status folds from
    self-hosted /wait actions carry the wrong orchestrator identity and are
    never cleared), so completion within the timeout IS the core assert."""
    epm = ExperimentPlanMaker()
    for _ in range(2):
        epm.add("SIM_websocket_data_hexid", {"wait_time": 2.0, "data_duration": 4.0})
    seq = Sequence(
        sequence_name="SIM_websocket_data_hexid_seq",
        sequence_label="p1b2b-item2",
        sequence_params={"wait_time": 2.0, "data_duration": 4.0},
        planned_experiments=epm.planned_experiments,
        sequence_uuid=gen_uuid(),
        dummy=True,
        simulation=True,
    )
    submit_and_start(orch_key, seq)
    wait_until(lambda: orch_parked(orch_key), 600, label="item2 full-run drain")
    hist = get_histories(orch_key)
    acts = [meta for _u, meta in hist["action"]]
    waits = [m for m in acts if m.get("action_name") == "wait"]
    assert len(waits) == 4, f"expected 4 self-hosted waits, got {len(waits)}"
    # self-hosted /wait finish under the renamed identity (MINOR-8)
    assert all(m.get("action_finished_timestamp") for m in waits), waits
    # status folds cleared: nothing lingers active
    st = get_orch_state(orch_key)
    assert str(st.get("loop_state")).endswith("stopped"), st.get("loop_state")
    exps = [meta for _u, meta in hist["experiment"]]
    assert len(exps) == 2, f"expected 2 experiments in history, got {len(exps)}"
    return 0


ITEMS["item2"] = item2_nondefault_identity


def item4_serial_multi_experiment(root: Path, orch_key: str, prefix: str) -> int:
    """§10.3 item 4: 3-experiment sequence; every experiment's actions all
    FINISH before the next experiment's first action STARTS (5c43a803),
    and the nonblocking registry is clear at park."""
    seq = build_ws_sequence(3, wait_time=2.0, data_duration=4.0)
    submit_and_start(orch_key, seq)
    wait_until(lambda: orch_parked(orch_key), 900, label="item4 3-exp drain")

    hist = get_histories(orch_key)
    acts = [meta for _u, meta in hist["action"]]
    groups: dict = {}
    for meta in acts:  # dict preserves first-seen (dispatch) order
        groups.setdefault(str(meta.get("experiment_uuid")), []).append(meta)
    exp_groups = list(groups.values())
    assert len(exp_groups) == 3, f"expected 3 experiment groups, got {len(exp_groups)}"
    for metas in exp_groups:
        assert all(
            m.get("action_finished_timestamp") for m in metas
        ), f"unfinished action in {metas}"
    for prev, nxt in zip(exp_groups, exp_groups[1:]):
        prev_finish = max(parse_hist_ts(m["action_finished_timestamp"]) for m in prev)
        next_start = min(parse_hist_ts(m["action_timestamp"]) for m in nxt)
        assert next_start >= prev_finish, (
            f"experiment overlap: next started {next_start} "
            f"before previous finished {prev_finish}"
        )
    nb = orch_post(orch_key, "list_nonblocking")
    assert nb == [], f"nonblocking registry not cleared: {nb}"
    exps = [meta for _u, meta in hist["experiment"]]
    assert len(exps) == 3, f"expected 3 experiments in history, got {len(exps)}"
    return 0


ITEMS["item4"] = item4_serial_multi_experiment


def _active_dict_nonempty() -> bool:
    gs = requests.post(
        f"http://{ORCH_HOST}:{ORCH_PORT}/global_status", timeout=10
    ).json()
    return bool(gs.get("active_dict"))


def item6_history_poll_hang_exit(root: Path, orch_key: str, prefix: str) -> int:
    """§10.3 item 6 (history-poll hang exit) — CHARACTERIZATION of a KNOWN P2
    DEFERRAL, not a passing behavioral test.

    Killing an action server mid-action SHOULD let the heartbeat monitor stop
    the orch. A P1b2b investigation showed this behavior exists in NEITHER the
    hexagon composition NOR legacy: the monitor (ServerMonitor.active_action_
    monitor, orch_monitor.py) fires and sets loop_intent=stop plus the
    "endpoints are unavailable" message via orch.stop(), but the single drainer
    is blocked in a dead-action wait with no health-aware escape (the hexagon
    dispatch poll waits on action_history, which the killed sim never feeds;
    and finish_active_experiment -> orch_wait_for_all_actions waits on
    active_dict, which nothing prunes for a dead peer), so loop_state never
    reaches stopped. A correct fix (health-aware dead-action exit + active_dict
    pruning) is native health-event decomposition, deferred to P2.

    This test therefore CHARACTERIZES the current limitation: after the kill
    the heartbeat monitor is observed to fire (best-effort) but the orch stays
    un-parked. TRIPWIRE: if a future P2 change makes the orch actually PARK
    stopped here, the ``assert not _stopped()`` below FAILS — that is the
    signal to rewrite this into the real behavioral assertion (orch parks
    stopped with the offline-endpoint message)."""
    seq = build_ws_sequence(1, wait_time=1.0, data_duration=60.0)
    submit_and_start(orch_key, seq)
    wait_until(_active_dict_nonempty, 120, poll_s=1.0, label="item6 action active")
    kill_server(root, prefix, "SIM")

    def _stopped() -> bool:
        return str(get_orch_state(orch_key).get("loop_state")).endswith("stopped")

    # Best-effort: the heartbeat monitor (interval 3s in goldenhexconc.yml)
    # should at least SET the offline-endpoint stop message, even though it
    # cannot park the loop for a dead peer.
    saw_msg = False
    for _ in range(15):  # ~30s of 2s polls
        msg = str(get_orch_state(orch_key).get("current_stop_message"))
        if "endpoints are unavailable" in msg:
            saw_msg = True
            break
        if _stopped():  # unexpected under the current limitation
            break
        time.sleep(2)
    print(f"[conc] item6 heartbeat monitor set offline message: {saw_msg}")

    # DOCUMENTED P2 GAP / TRIPWIRE: the orch cannot yet convert the stop intent
    # into a parked stopped state for a dead peer. Give it a generous window;
    # it must stay un-parked under the current (legacy-parity) behavior.
    for _ in range(15):  # ~30s more
        if _stopped():
            break
        time.sleep(2)
    assert not _stopped(), (
        "item6: orch PARKED stopped after a dead-peer kill — the P2 dead-peer "
        "health-aware exit appears to be implemented. Update this test to the "
        "real behavioral assertion (orch parks stopped with the "
        "'endpoints are unavailable' message)."
    )
    return 0


ITEMS["item6"] = item6_history_poll_hang_exit


def item7_idle_drain_and_history(root: Path, orch_key: str, prefix: str) -> int:
    """§10.3 item 7: natural drain (NO /stop) parks the loop via the
    complete-idle path; history entries are non-blank. Plus the launched-
    path §9.1 asserts: flat per-server log files under <root>/LOGS."""
    seq = build_ws_sequence(1, wait_time=2.0, data_duration=4.0)
    submit_and_start(orch_key, seq)
    # deliberately NO orch_post(..., "stop"): the drain itself must park
    wait_until(lambda: orch_parked(orch_key), 600, label="item7 natural drain")
    st = get_orch_state(orch_key)
    assert str(st.get("loop_state")).endswith("stopped"), st.get("loop_state")
    assert str(st.get("orch_state")).endswith("idle"), st.get("orch_state")

    hist = get_histories(orch_key)
    acts = [meta for _u, meta in hist["action"]]
    assert acts, "action history is empty after a completed run"
    for meta in acts:  # non-blank entries (2e828981/ac42e9bf/6b8931ce)
        assert meta.get("action_name"), meta
        assert meta.get("action_timestamp"), meta
        assert meta.get("action_finished_timestamp"), meta
        assert meta.get("experiment_uuid"), meta

    # §9.1 on the launched hexagon path: flat log files at the contract path
    logs = root / "LOGS"
    for key in (orch_key, "SIM", "DB"):
        assert (logs / f"{key}.log").exists(), f"missing {key}.log under LOGS"
    assert (logs / "ntpLastSync.txt").exists()
    assert not (root / "LOGS_FW").exists(), "parallel log dir must never exist"
    return 0


ITEMS["item7"] = item7_idle_drain_and_history


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--item", required=True, choices=sorted(ITEMS) or ["none"])
    ap.add_argument("--root", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--orch-key", default="ORCH")
    args = ap.parse_args()
    try:
        rc = ITEMS[args.item](Path(args.root), args.orch_key, args.prefix)
    except AssertionError as e:
        print(f"[conc] {args.item} ASSERT FAIL: {e}")
        return 1
    except Exception as e:  # noqa: BLE001 — driver boundary
        print(f"[conc] {args.item} driver error: {e!r}")
        return 2
    print(f"[conc] {args.item} -> rc {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
