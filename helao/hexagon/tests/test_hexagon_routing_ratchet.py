"""B7c (D-B7c.11): hexagon routing and the adapters.legacy package stay gone.

Static half: no tracked file in this repo, nor in any private deployment checked out
under helao/deploy/, carries the routing vocabulary B7c retired, and no smoke file names
a config that no longer exists. Runtime half: neither deleted package can be imported,
which also catches the untracked __pycache__ directory a pull leaves behind (D-B7b.9).
Specs, plans, the two station runbooks (E2) and nested docs/ are provenance
(D-B7b.10) and are not scanned.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterator

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
THIS = "helao/hexagon/tests/test_hexagon_routing_ratchet.py"

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("legacy_module key", re.compile(r"legacy_module")),
    (
        "graft code key",
        re.compile(r"""["']?(fast|bokeh|reflex)["']?\s*:\s*["']?graft\b"""),
    ),
    (
        "deployment: hexagon",
        re.compile(r"""["']?deployment["']?\s*:\s*["']?hexagon\b"""),
    ),
    ("shim package path", re.compile(r"helao[./]deploy[./]hexagon")),
    ("adapters.legacy path", re.compile(r"adapters[./]legacy")),
    (
        "deleted symbol",
        re.compile(
            r"hexagon_variant|hexconfig|makeActionApp|makeVisApp|reflex_host|VIS_REQUIRED"
        ),
    ),
)
#: E1: preflight must detect, and its tests must feed, the three keys.
KEY_PATTERNS_EXEMPT = {
    "helao/hexagon/preflight.py",
    "helao/hexagon/tests/test_preflight.py",
}
KEY_PATTERNS = {"legacy_module key", "graft code key", "deployment: hexagon"}
#: E2: runbooks whose earlier dated sections are provenance (§8).
HISTORICAL_PARENT = (
    "docs/superpowers/specs/",
    "docs/superpowers/plans/",
    "docs/superpowers/notes/2026-08-15-B5-station-gate-runbook.md",
    "docs/superpowers/notes/2026-08-08-P7-station-rollout-runbook.md",
)
ADAPTERS_DIR = "helao/hexagon/adapters/"
LEGACY_SUBPKG = re.compile(r"\blegacy/")
HEX_TOKEN = re.compile(r"\b\w+(?:gold)?hex\b")
#: E3: a smoke token may name any config of the same repo.
CONFIG_FILE = re.compile(r"(?:^|/)configs/([^/]+)\.(?:yml|py)$")
SUFFIXES = {".py", ".yml", ".yaml", ".bat", ".sh", ".md", ".toml", ".json"}


def _git_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True
    ).stdout.decode("utf-8")
    return [p for p in out.split("\0") if p]


def _walk_files(root: Path) -> list[str]:
    rels = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and d != "__pycache__"
        ]
        rels += [
            (Path(dirpath) / f).relative_to(root).as_posix()
            for f in filenames
            if Path(f).suffix in SUFFIXES
        ]
    return rels


def repos(root: Path = REPO_ROOT) -> Iterator[tuple[str, Path, list[str]]]:
    """The parent, then each private deployment present on disk."""
    yield "parent", root, _git_files(root)
    for d in sorted((root / "helao" / "deploy").iterdir()):
        if (
            not d.is_dir()
            or d.name.startswith(".")
            or d.name in ("hte", "test", "__pycache__")
        ):
            continue  # helao/deploy/.omc/ holds agent state, not a deployment
        files = _git_files(d) if (d / ".git").exists() else _walk_files(d)
        yield f"deploy/{d.name}", d, files


def _historical(rel: str, nested: bool) -> bool:
    if nested:
        return rel.startswith("docs/")
    return rel == THIS or rel.startswith(HISTORICAL_PARENT)


def scan_text(
    label: str, rel: str, text: str, nested: bool, configs: set[str]
) -> list[str]:
    """Every retired form in one file's text. Pure, so the self-tests can feed it."""
    hits = []
    smoke = "tests/smoke/" in f"/{rel}"
    for n, line in enumerate(text.splitlines(), 1):
        where = f"{label}:{rel}:{n}"
        for name, pat in PATTERNS:
            if name in KEY_PATTERNS and not nested and rel in KEY_PATTERNS_EXEMPT:
                continue
            if pat.search(line):
                hits.append(f"{where}: {name}: {line.strip()[:120]}")
        if not nested and rel.startswith(ADAPTERS_DIR) and LEGACY_SUBPKG.search(line):
            hits.append(f"{where}: adapters legacy/ subpackage: {line.strip()[:120]}")
        if smoke:
            for tok in HEX_TOKEN.findall(line):
                if tok not in configs:
                    hits.append(f"{where}: smoke leftover '{tok}' names no config")
    return hits


def scan(label: str, root: Path, files: list[str]) -> list[str]:
    nested = label != "parent"
    configs = {m.group(1) for f in files if (m := CONFIG_FILE.search(f))}
    hits = []
    for rel in files:
        if _historical(rel, nested):
            continue
        if CONFIG_FILE.search(rel) and rel.endswith("_hex.py"):
            hits.append(f"{label}:{rel}: a *_hex.py variant config")
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits += scan_text(label, rel, text, nested, configs)
    return hits


def test_no_hexagon_routing_vocabulary_anywhere() -> None:
    hits = [h for label, root, files in repos() for h in scan(label, root, files)]
    assert not hits, (
        f"{len(hits)} retired hexagon-routing reference(s) (B7c, D-B7c.11). A config "
        "names its module in fast:/bokeh: and adds deployment: only where preflight "
        "reports it ambiguous; adapters live in helao.hexagon.adapters.shared.\n"
        + "\n".join(hits[:80])
    )


SAMPLES = [
    (
        "x.yml",
        "    legacy_module: helao.deploy.hte.servers.action.x",
        "legacy_module key",
    ),
    ("x.yml", "    fast: graft", "graft code key"),
    ("x.py", '        "bokeh": "graft",', "graft code key"),
    ("x.yml", "    deployment: hexagon", "deployment: hexagon"),
    ("x.py", "        'deployment': 'hexagon',", "deployment: hexagon"),
    ("x.py", "from helao.deploy.hexagon.servers import x", "shim package path"),
    (
        "x.py",
        "from helao.hexagon.adapters.legacy.clock import C",
        "adapters.legacy path",
    ),
    ("x.md", "see helao/hexagon/adapters/legacy/status.py", "adapters.legacy path"),
    ("x.py", "app = makeActionApp(key)", "deleted symbol"),
    ("x.py", "config = hexagon_variant(base)", "deleted symbol"),
    (
        "helao/hexagon/adapters/x.py",
        "the legacy/ subpackage",
        "adapters legacy/ subpackage",
    ),
    ("helao/hexagon/tests/smoke/x.sh", "launch andorhex", "smoke leftover"),
]


@pytest.mark.parametrize("rel,line,expect", SAMPLES)
def test_the_scanner_flags_each_retired_form(rel: str, line: str, expect: str) -> None:
    hits = scan_text("parent", rel, line, False, {"andor", "andorgold"})
    assert any(expect in h for h in hits), hits


def test_the_scanner_spares_live_names_and_provenance() -> None:
    assert (
        scan_text(
            "parent",
            "x.yml",
            "    fast: ws_simulator\n    deployment: test",
            False,
            set(),
        )
        == []
    )
    assert (
        scan_text(
            "parent",
            "helao/hexagon/tests/smoke/x.sh",
            "goldenhex",
            False,
            {"goldenhex"},
        )
        == []
    )
    assert _historical("docs/superpowers/specs/x.md", False)
    assert _historical("docs/x.md", True)
    assert not _historical("docs/config-schema.md", False)


def test_the_nested_walk_scans_deployments_and_spares_docs_and_dot_dirs(
    tmp_path: Path,
) -> None:
    dep = tmp_path / "helao" / "deploy" / "fake"
    for rel, text in {
        "configs/a.yml": "legacy_module: x\n",
        "docs/old.md": "legacy_module: x\n",
        "helao/hexagon/preflight.py": "deployment: hexagon\n",
        ".omc/state.md": "legacy_module: x\n",
    }.items():
        (dep / rel).parent.mkdir(parents=True, exist_ok=True)
        (dep / rel).write_text(text, encoding="utf-8")
    (tmp_path / "helao" / "deploy" / "hte").mkdir()
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    nested = [(lbl, r, f) for lbl, r, f in repos(tmp_path) if lbl != "parent"]
    assert len(nested) == 1
    label, root, files = nested[0]
    hits = sorted(h.split(": ", 1)[0] for h in scan(label, root, files))
    assert hits == [
        f"{label}:configs/a.yml:1",
        f"{label}:helao/hexagon/preflight.py:1",
    ]


_GONE_PROBE = r"""
import importlib.util, json
mods = ("helao.deploy.hexagon", "helao.hexagon.adapters.legacy")
print("B7C-GONE " + json.dumps({m: importlib.util.find_spec(m) is not None for m in mods}))
"""


def test_the_retired_packages_cannot_be_imported() -> None:
    """A pull that deletes the tracked files leaves __pycache__ behind, and the leftover
    directory imports as a namespace package. A fresh interpreter, PYTHONPATH = repo root.
    """
    proc = subprocess.run(
        [sys.executable, "-c", _GONE_PROBE],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("B7C-GONE ")]
    assert proc.returncode == 0 and len(lines) == 1, proc.stderr[-4000:]
    found = json.loads(lines[0][len("B7C-GONE ") :])
    assert not any(found.values()), (
        f"still importable: {[m for m, v in found.items() if v]}. Remove the leftover "
        "directories once, from the repo root: `rm -rf helao/deploy/hexagon "
        "helao/hexagon/adapters/legacy` (Linux), or `rmdir /s /q helao\\deploy\\hexagon` "
        "and `rmdir /s /q helao\\hexagon\\adapters\\legacy` (Windows cmd)."
    )
