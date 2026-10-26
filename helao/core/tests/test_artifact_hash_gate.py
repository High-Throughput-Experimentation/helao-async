"""Every record write outside the finalization seam logs a rehash (spec §5)."""

import ast
import subprocess
from pathlib import Path

WRITERS = {"write_meta"}
HASHERS = {"log_artifact_hashes", "log_artifact_hashes_sync"}
# (file, function) -> why no rehash is needed there
ALLOW = {
    (
        "helao/core/drivers/data/analysis_layout.py",
        "write_model_json",
    ): "hashed at the end of publish_outputs, which every analysis publish calls",
    (
        "helao/hexagon/adapters/native/data_file.py",
        "*",
    ): "data .meta.json header, rewritten on every write_file; hashed at action finalization",
    (
        "helao/hexagon/adapters/native/posthoc_writer.py",
        "*",
    ): "data .meta.json header; hashed at action finalization",
    (
        "helao/hexagon/adapters/native/sync_driver.py",
        "write_meta",
    ): "method named write_meta (the .prg sidecar), not a record writer",
}


def _called(fn) -> set:
    names = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            names.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", None))
    return names


def _files():
    root = Path(__file__).resolve().parents[3]
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "*.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [
        (root, p)
        for p in out.split()
        if not Path(p).name.startswith("test_")
        and not p.startswith("harness/")
        and "/smoke/" not in p
    ]


def test_record_writes_rehash_or_are_allowlisted():
    bad = []
    for root, path in _files():
        tree = ast.parse((root / path).read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            called = _called(fn)
            if called & WRITERS and not called & HASHERS:
                if (path, fn.name) in ALLOW or (path, "*") in ALLOW:
                    continue
                bad.append(f"{path}:{fn.lineno} {fn.name}")
    assert not bad, "record write without log_artifact_hashes:\n" + "\n".join(bad)


def test_gate_catches_a_planted_site():
    src = "def f(p, d):\n    write_meta(p, d)\n"
    fn = ast.parse(src).body[0]
    assert _called(fn) & WRITERS and not _called(fn) & HASHERS
