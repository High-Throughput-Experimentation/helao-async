"""P1b1 smoke assertions: the GM-1 run left a complete, quiesced tree.
Wiring proof only -- normalized parity diffs are P1b2."""

import sys
from pathlib import Path


def main(root: str) -> int:
    root_p = Path(root)
    failures = []

    def check(cond: bool, msg: str):
        (print(f"  OK  {msg}") if cond else failures.append(msg))

    # 1. sequence shipped end-to-end: RUNS_SYNCED holds the destructive zip
    zips = list((root_p / "RUNS_SYNCED").rglob("*.zip"))
    check(len(zips) >= 1, f"RUNS_SYNCED sequence zip present ({zips})")

    # 2. process leg ran: GM-1 = 2 experiments x 2 process groups -> 4 prc ymls
    prcs = list((root_p / "PROCESSES").rglob("*-prc.yml"))
    check(len(prcs) == 4, f"PROCESSES has 4 -prc.yml (got {len(prcs)})")

    # 3. recorded S3 sink got payloads (sim DB s3_record mode)
    s3 = list((root_p / "S3_SIM").rglob("*")) if (root_p / "S3_SIM").is_dir() else []
    check(len(s3) > 0, "S3_SIM recorded uploads present")

    # 4. quiesced: nothing stranded in RUNS_ACTIVE
    active = list((root_p / "RUNS_ACTIVE").rglob("*.yml"))
    check(len(active) == 0, f"RUNS_ACTIVE empty (got {active})")

    # 5. logging contract (F3): flat per-server logs under <root>/LOGS
    for key in ("ORCH", "SIM", "DB"):
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
