"""Find writer folders whose README lacks an ``## Outputs`` section.

A *unit* is ``servers/<name>/``, ``scripts/<name>/`` or ``processors/`` under a
deployment root. A unit whose Python matches :data:`WRITER` writes or publishes data,
so its ``README.md`` must catalog those outputs under ``## Outputs``. This is a
presence check only; review checks the content.
"""

import re
from collections.abc import Iterable
from pathlib import Path

# ponytail: static regex, misses writers that go through an unlisted helper;
# callers name those units in ``extra``.
WRITER = re.compile(
    r"enqueue_data|write_live_data|write_file(?:_nowait)?\(|json_data_keys"
    r"|action_output_dir|action_params\[[^\]]+\]\s*=(?!=)|action_output\["
    r"|\.to_parquet\(|write_to_dataset\(|write_table\(|\.to_csv\(|savefig\("
    r"|np\.save|AnalysisOutput\b|\boutputs\s*=|DriverPoller|json\.dump\("
    r"|\.write_text\(|\.write_bytes\(|open\([^)]*[\"']w|ZipFile\(|write_point_map\("
)
UNIT_DIRS = ("servers", "scripts", "processors")
SKIP_DIRS = {"tests", "__pycache__", ".pixi"}
OUTPUTS_HEADING = re.compile(r"^## Outputs\s*$", re.M)


def unit_of(rel: Path) -> Path | None:
    """Return the unit folder that owns ``rel`` (a path relative to a deployment)."""
    parts = rel.parts
    if not parts or parts[0] not in UNIT_DIRS or SKIP_DIRS & set(parts):
        return None
    if parts[0] == "processors":
        return Path("processors")
    return Path(*parts[:2]) if len(parts) > 2 else None


def missing_outputs_sections(root: Path, extra: Iterable[str] = ()) -> list[str]:
    """Return units under ``root`` that write data but document no outputs."""
    units = {Path(u) for u in extra}
    for py in root.rglob("*.py"):
        unit = unit_of(py.relative_to(root))
        if unit is None or unit in units:
            continue
        if WRITER.search(py.read_text(encoding="utf-8", errors="replace")):
            units.add(unit)
    missing = []
    for unit in sorted(units):
        readme = root / unit / "README.md"
        text = readme.read_text(encoding="utf-8") if readme.is_file() else ""
        if not OUTPUTS_HEADING.search(text):
            missing.append(unit.as_posix())
    return missing
