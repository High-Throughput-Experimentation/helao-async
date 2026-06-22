"""Framework merge gate.

Runs the helao/framework pytest suite under coverage, then enforces a
minimum coverage percentage on the gated layers (domain + models + support).
A per-module >=90% bar for support/ is additionally enforced by
tests/test_support_coverage_bar.py.

Run with the helao conda env, e.g.:
    conda run -n helao python run_framework_tests.py
"""
import json
import subprocess
import sys
from pathlib import Path

from helao.framework._devtools.coverage_gate import (
    GATED_PREFIXES,
    gate_passes,
    summarize,
)

THRESHOLD = 90.0
COV_JSON = Path(".framework-cov.json")


def main() -> int:
    pytest_cmd = [
        sys.executable, "-m", "pytest",
        "helao/framework/tests",
        "--cov=helao/framework",
        "--cov-report=", f"--cov-report=json:{COV_JSON}",
    ]
    result = subprocess.run(pytest_cmd)
    if result.returncode not in (0, 5):  # 5 == no tests collected
        print(f"[gate] pytest failed (exit {result.returncode})")
        return result.returncode

    if not COV_JSON.exists():
        print("[gate] no coverage report produced; nothing to gate")
        return 0

    cov_json = json.loads(COV_JSON.read_text(encoding="utf-8"))
    covered, total = summarize(cov_json, GATED_PREFIXES)
    if total == 0:
        print("[gate] gated layers (domain+models+support) have no statements yet — PASS")
        return 0

    pct = (covered / total) * 100.0
    ok = gate_passes(cov_json, THRESHOLD, GATED_PREFIXES)
    status = "PASS" if ok else "FAIL"
    print(f"[gate] domain+models+support coverage: {covered}/{total} = {pct:.1f}% (>= {THRESHOLD}%? {status})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
