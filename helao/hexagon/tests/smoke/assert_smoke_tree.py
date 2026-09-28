"""P1b1 smoke assertions: the GM-1 run left a complete, quiesced tree.
Wiring proof only -- normalized parity diffs are P1b2."""

import sys
import zipfile
from pathlib import Path

from helao.helpers.run_state import RunStateJournal, _prg_is_complete


def main(root: str) -> int:
    root_p = Path(root)
    failures = []

    def check(cond: bool, msg: str):
        (print(f"  OK  {msg}") if cond else failures.append(msg))

    # 1. sequence shipped end-to-end. A record no longer moves or archives, so
    # "shipped" is a complete .prg sidecar beside a -seq.yml that is still in
    # the one place it was ever written. Asserting the absence of a zip is half
    # the check: the promotion and the zip were the same deleted step, and a zip
    # reappearing means a legacy mover is still live.
    seqs = list((root_p / "RUNS").rglob("*-seq.yml"))
    check(len(seqs) >= 1, f"RUNS holds a -seq.yml ({seqs})")
    unshipped = [str(s) for s in seqs if not _prg_is_complete(s.with_suffix(".prg"))]
    check(not unshipped, f"every -seq.yml has a complete .prg beside it ({unshipped})")
    check(not list(root_p.rglob("*.zip")), "no sequence zip anywhere under root")

    # 2. process leg ran: GM-1 = 2 experiments x 2 process groups -> 4 prc ymls
    # Processes are written beside their -exp.yml, so a fully synced sequence
    # carries them INSIDE its zip: zip_dir deletes the source directory on
    # success, so a filesystem glob alone finds none of them. Count both --
    # loose ones (a sequence not yet zipped) and zip members.
    prcs = [str(p) for p in root_p.rglob("*-prc.yml") if "PROCESSES" not in p.parts]
    for z in sorted(root_p.rglob("*.zip")):
        with zipfile.ZipFile(z) as zf:
            prcs += [f"{z.name}:{n}" for n in zf.namelist() if n.endswith("-prc.yml")]
    check(len(prcs) == 4, f"run tree and any zips hold 4 -prc.yml (got {len(prcs)})")
    stale = list((root_p / "PROCESSES").rglob("*-prc.yml"))
    check(not stale, f"PROCESSES must gain nothing (got {len(stale)})")

    # 3. recorded S3 sink got payloads (sim DB s3_record mode)
    s3 = list((root_p / "S3_SIM").rglob("*")) if (root_p / "S3_SIM").is_dir() else []
    check(len(s3) > 0, "S3_SIM recorded uploads present")

    # 4. quiesced. There is no longer an in-flight tree to be empty, and
    # "RUNS_ACTIVE is empty" would now pass over a directory that was never
    # created -- a clean verdict from a tree never entered. State lives in the
    # per-server journals, so quiesced means every journal replays to nothing.
    journals = sorted((root_p / "STATES").glob("runstate_*.jsonl"))
    check(bool(journals), f"per-server run-state journals exist ({journals})")
    for j in journals:
        left = RunStateJournal(root_p / "STATES", j.stem[len("runstate_") :])
        ws = left.working_set()
        check(not ws, f"{j.name} replays empty (got {sorted(ws)})")

    # 5. logging contract (F3): flat per-server logs under <root>/LOGS
    for key in ("ORCH", "SIM", "SYNC"):
        check((root_p / "LOGS" / f"{key}.log").is_file(), f"LOGS/{key}.log exists")

    # 6. the hexagon loop actually ran (its parked/started log line)
    orch_log = (root_p / "LOGS" / "ORCH.log").read_text(errors="replace")
    check("--- started operator orch ---" in orch_log, "hexagon loop started")
    check("FAKE PORT IN USE" not in orch_log, "no fake adapters in composition")
    check("Traceback" not in orch_log, "no tracebacks in ORCH.log")

    if failures:
        print("\nSMOKE FAILURES:")
        for f in failures:
            print(f"  FAIL {f}")
        return 1
    print("\nP1b1 smoke tree: ALL CHECKS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
