"""§10.3 launched-group concurrency drivers (items 2/4/6/7, P1b2b).

Runs against a LIVE launched group (launch.py <prefix>) — MAIN SESSION only
(background subagent launches get reaped on idle). Invoked by conc_run.sh.
Exit code: 0 PASS, 1 assertion failure, 2 driver error.

Item drivers are registered in ITEMS and appended by Tasks 8-11:
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
# Tasks 8-11 register: ITEMS["item2"], ITEMS["item4"], ITEMS["item6"], ITEMS["item7"]
# Signature: (root, orch_key, prefix) -> rc


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
