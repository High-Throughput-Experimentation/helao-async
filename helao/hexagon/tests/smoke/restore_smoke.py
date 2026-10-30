"""Restore smoke driver (C2 gate): export queues mid-run, restart with --restore, run to park.

Not a test (``run_tests.py`` reports it as NOTESTS). Phases, selected with ``--phase``:

  export         append a 3-experiment WS sequence, start, wait until experiment 2 is running
  verify-export  load STATES/queues.pck after the group was killed, write a JSON summary
  restore        after ``launch.py --restore``: check the pck was consumed, start, run to park,
                 write a JSON summary of fields that are stable from run to run

MAIN SESSION ONLY: it talks to a launched ``goldenhex`` group on 127.0.0.1:8001.
"""

import argparse
import collections
import glob
import json
import os
import pickle
import re
import sys

from helao.helpers.meta_io import meta_glob, read_meta
from helao.hexagon.tests.smoke.conc_items import (
    build_ws_sequence,
    get_orch_state,
    orch_parked,
    orch_post,
    wait_until,
)

ORCH = "ORCH"
TS_RE = re.compile(r"\d{6}\.\d{6}")


def _exp_records(root: str) -> list:
    return meta_glob(os.path.join(root, "RUNS"), "exp", "**/*")


def _act_records(root: str) -> list:
    return meta_glob(os.path.join(root, "RUNS"), "act", "**/*")


def phase_export(root: str) -> int:
    seq = build_ws_sequence(n_exps=3, wait_time=2.0, data_duration=4.0)
    orch_post(ORCH, "append_sequence", body={"sequence": seq.as_dict()})
    orch_post(ORCH, "start")

    def second_exp_running() -> bool:
        st = get_orch_state(ORCH)
        return bool(st.get("active_experiment")) and len(_exp_records(root)) >= 2

    wait_until(second_exp_running, 120, poll_s=0.5, label="second experiment running")
    print("READY-TO-KILL")
    return 0


def phase_verify_export(root: str, out: str) -> int:
    pck = os.path.join(root, "STATES", "queues.pck")
    assert os.path.isfile(pck), f"{pck} missing"
    with open(pck, "rb") as f:
        d = pickle.load(f)
    active = d["globalstatusmodel"].active_dict
    summary = {
        "schema": d.get("schema"),
        "len_seq": len(d["seq"]),
        "len_exp": len(d["exp"]),
        "len_act": len(d["act"]),
        "active_experiment_name": getattr(d["active_exp"], "experiment_name", None),
        "active_dict_nonempty": bool(active),
        "inflight_action_names": sorted(a.action_name for a in active.values()),
    }
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    print(json.dumps(summary, sort_keys=True))
    return 0


def phase_restore(root: str, out: str) -> int:
    states = os.path.join(root, "STATES")
    assert not os.path.exists(
        os.path.join(states, "queues.pck")
    ), "queues.pck still present"
    imported = glob.glob(os.path.join(states, "queues_imported_*.pck"))
    assert len(imported) == 1, f"expected 1 queues_imported_*.pck, found {imported}"
    loop = str(get_orch_state(ORCH).get("loop_state"))
    assert loop.endswith("stopped"), f"loop_state after restore is {loop!r}"
    orch_post(ORCH, "start")
    wait_until(lambda: orch_parked(ORCH), 300, label="orch_parked")

    exps = _exp_records(root)
    acts = collections.defaultdict(list)
    skipped_finished = 0
    for p in _act_records(root):
        a = read_meta(p)
        status = [str(getattr(s, "value", s)) for s in a.get("action_status", [])]
        acts[a["action_name"]].append(
            json.dumps([status, a.get("action_retry")], sort_keys=True)
        )
        if status == ["skipped", "finished"]:
            skipped_finished += 1
    summary = {
        "n_exp": len(exps),
        "experiment_status": sorted(
            json.dumps(
                [
                    str(getattr(s, "value", s))
                    for s in read_meta(p).get("experiment_status", [])
                ]
            )
            for p in exps
        ),
        "actions": {k: sorted(v) for k, v in sorted(acts.items())},
        "n_skipped_finished": skipped_finished,
        "states_patterns": sorted({TS_RE.sub("<TS>", n) for n in os.listdir(states)}),
    }
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    print(json.dumps(summary, sort_keys=True))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--phase", required=True, choices=["export", "verify-export", "restore"]
    )
    ap.add_argument("--root", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.phase == "export":
        return phase_export(a.root)
    if not a.out:
        ap.error("--out is required for this phase")
    if a.phase == "verify-export":
        return phase_verify_export(a.root, a.out)
    return phase_restore(a.root, a.out)


if __name__ == "__main__":
    sys.exit(main())
