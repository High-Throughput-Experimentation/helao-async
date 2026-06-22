"""Coverage-threshold math for the framework merge gate.

Parses coverage.py JSON (`coverage json`) and enforces a minimum percentage
on the gated layers only (domain + models). Empty gated layers pass.
"""
from typing import Iterable, Mapping

# Path prefixes the coverage threshold applies to.
GATED_PREFIXES: tuple[str, ...] = (
    "helao/framework/domain/",
    "helao/framework/models/",
)


def _normalize(path: str) -> str:
    return path.replace("\\", "/")


def summarize(cov_json: Mapping, prefixes: Iterable[str]) -> tuple[int, int]:
    """Return (covered_lines, num_statements) summed over gated files.

    A file is gated if its normalized path starts with any of `prefixes`.
    """
    prefixes = tuple(prefixes)
    covered = 0
    total = 0
    for path, entry in cov_json.get("files", {}).items():
        if _normalize(path).startswith(prefixes):
            summary = entry.get("summary", {})
            covered += int(summary.get("covered_lines", 0))
            total += int(summary.get("num_statements", 0))
    return covered, total


def gate_passes(cov_json: Mapping, threshold: float, prefixes: Iterable[str]) -> bool:
    """True if gated coverage >= threshold percent (or no gated statements exist)."""
    covered, total = summarize(cov_json, prefixes)
    if total == 0:
        return True
    return (covered / total) * 100.0 >= threshold
