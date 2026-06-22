"""Enforces the per-support-module >=90% line-coverage bar.

The merge gate (run_framework_tests.py) aggregates coverage across gated
prefixes, which cannot catch a single under-covered module. This test reads
the coverage.py JSON report and asserts that EVERY module under
``helao/framework/support/`` individually meets the 90% line-coverage bar
required by the SP2 spec (§5).

It is a no-op when the coverage report is absent (e.g. a plain pytest run
without --cov), so it never blocks ad-hoc test runs; the merge gate always
produces the report, so the bar is enforced there.
"""
import json
from pathlib import Path

import pytest

COV_JSON = Path(".framework-cov.json")
SUPPORT_PREFIX = "helao/framework/support/"
THRESHOLD = 90.0


def _module_line_coverage() -> dict[str, float]:
    cov = json.loads(COV_JSON.read_text(encoding="utf-8"))
    out: dict[str, float] = {}
    for path, entry in cov.get("files", {}).items():
        norm = path.replace("\\", "/")
        if not norm.startswith(SUPPORT_PREFIX):
            continue
        summary = entry.get("summary", {})
        stmts = int(summary.get("num_statements", 0))
        covered = int(summary.get("covered_lines", 0))
        out[norm] = 100.0 if stmts == 0 else (covered / stmts) * 100.0
    return out


@pytest.mark.skipif(
    not COV_JSON.exists(),
    reason="coverage report absent; per-module bar enforced under --cov / merge gate",
)
def test_every_support_module_meets_90pct():
    per_module = _module_line_coverage()
    assert per_module, "no support/ modules found in coverage report"
    under = {m: pct for m, pct in per_module.items() if pct < THRESHOLD}
    assert not under, f"support modules below {THRESHOLD}%: " + ", ".join(
        f"{m}={pct:.1f}%" for m, pct in sorted(under.items())
    )
