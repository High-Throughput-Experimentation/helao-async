"""Move files per a JSON mapping with ``git mv`` and rewrite imports to match.

    python -m harness.reorg_deploy <mapping.json> [--dry-run]

Mapping: ``{"scan": [roots...], "moves": [[src, dst], ...]}``, paths relative to
the repo root. Every ``import``/``from`` statement in scanned ``.py`` files is
resolved against the importing file's OLD module name and rewritten to the
target's NEW absolute path. A relative import that still resolves to the target's
new module from the importer's new location is kept as it is. String literals and
non-Python files are never rewritten: matches in scanned ``.py`` files are listed
as leftovers for a person to fix, as is ``from pkg import submodule`` where the
submodule moved but ``pkg`` did not (prefixed ``MANUAL``).
Directories holding their own ``.git`` (nested private repos) are not scanned
in move mode. To fix a nested repo's imports of the moved modules, run
``--rewrite-only --scan <dir> <mapping.json>...``: no files move, the old->new
module map comes from the mappings' moves (a source without a suffix is a package
prefix), and every ``.py`` under ``<dir>`` is rewritten even inside a nested repo.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SKIP = {"__pycache__", ".omc", ".ruff_cache", ".git"}


@dataclass
class Report:
    moved: list[tuple[str, str]] = field(default_factory=list)
    rewritten: list[str] = field(default_factory=list)
    leftovers: list[str] = field(default_factory=list)


def load_mapping(path: Path) -> tuple[list[str], list[tuple[Path, Path]]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("scan", ["helao", "harness"]), [
        (Path(s), Path(d)) for s, d in data["moves"]
    ]


def _pairs(moves, repo_root: Path) -> list[tuple[Path, Path]]:
    out: list[tuple[Path, Path]] = []
    for src, dst in moves:
        full = repo_root / src
        if full.is_dir():
            for f in sorted(full.rglob("*")):
                if f.is_file() and not SKIP & set(f.relative_to(full).parts):
                    out.append((src / f.relative_to(full), dst / f.relative_to(full)))
        elif full.is_file():
            out.append((src, dst))
        else:
            raise FileNotFoundError(f"mapping source missing: {src}")
    return out


def expand(moves, repo_root: Path) -> dict[Path, Path]:
    return dict(_pairs(moves, repo_root))


def preflight(moves, repo_root: Path) -> None:
    """Raise ValueError listing every problem; touches nothing."""
    pairs = _pairs(moves, repo_root)
    tracked = set(
        subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split("\0")
    )
    problems = []
    for seen, label, idx in ((set(), "source", 0), (set(), "destination", 1)):
        for pair in pairs:
            if pair[idx] in seen:
                problems.append(f"{label} listed twice: {pair[idx]}")
            seen.add(pair[idx])
    for src, dst in pairs:
        if (repo_root / dst).exists():
            problems.append(f"destination exists: {dst}")
        if src.as_posix() not in tracked:
            problems.append(f"source not tracked by git: {src}")
    if problems:
        raise ValueError("reorg preflight failed:\n" + "\n".join(problems))


def module_name(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _modmap(files: dict[Path, Path]) -> dict[str, str]:
    return {
        module_name(s): module_name(d) for s, d in files.items() if s.suffix == ".py"
    }


def _new(target: str, modmap: dict[str, str]) -> str:
    """Map an old absolute module to its new name, longest prefix first."""
    parts = target.split(".")
    for i in range(len(parts), 0, -1):
        head = ".".join(parts[:i])
        if head in modmap:
            return ".".join([modmap[head], *parts[i:]])
    return target


def _absolute(level: int, module: str | None, own: str, is_package: bool) -> str:
    base = own.split(".")
    if not is_package:
        base = base[:-1]
    base = base[: len(base) - (level - 1)]
    return ".".join([*base, *([module] if module else [])])


_FROM = re.compile(r"^(\s*from\s+)(\.*[\w.]*)(\s+import\b)")


def rewrite_source(
    text: str,
    own_old: str,
    own_new: str,
    is_package: bool,
    modmap: dict[str, str],
    manual: list[int] | None = None,
) -> str:
    """Rewrite imports for a file moving ``own_old`` -> ``own_new``.

    ``manual`` collects line numbers of ``from pkg import sub`` where ``sub``
    moved but ``pkg`` did not; those are not rewritten.
    """
    lines = text.splitlines(keepends=True)
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom):
            old_abs = (
                _absolute(node.level, node.module, own_old, is_package)
                if node.level
                else node.module or ""
            )
            new_abs = _new(old_abs, modmap)
            if node.level:
                rel_new = _absolute(node.level, node.module, own_new, is_package)
                if all(
                    _new(f"{old_abs}.{a.name}", modmap) == f"{rel_new}.{a.name}"
                    for a in node.names
                ):
                    continue  # every imported name still resolves from here
            if manual is not None and any(
                _new(f"{old_abs}.{a.name}", modmap) != f"{new_abs}.{a.name}"
                for a in node.names
            ):
                manual.append(node.lineno)
            if node.level:
                if new_abs == rel_new:
                    continue  # the relative import still resolves to the target
            elif new_abs == old_abs:
                continue
            i = node.lineno - 1  # a multi-line import: only this first line changes
            lines[i] = _FROM.sub(lambda m: f"{m[1]}{new_abs}{m[3]}", lines[i], count=1)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                new = _new(alias.name, modmap)
                if new != alias.name:
                    i = alias.lineno - 1
                    lines[i] = re.sub(
                        rf"(?<![\w.]){re.escape(alias.name)}(?![\w])",
                        new,
                        lines[i],
                        count=1,
                    )
    return "".join(lines)


def _scan_files(
    repo_root: Path, roots: list[str], skip_nested: bool = True
) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if any(ch in root for ch in "*?"):
            files += sorted(repo_root.glob(root))
            continue
        for f in sorted((repo_root / root).rglob("*.py")):
            rel_parts = f.relative_to(repo_root).parts
            if SKIP & set(rel_parts):
                continue
            if skip_nested and any(
                (repo_root.joinpath(*rel_parts[:k]) / ".git").exists()
                for k in range(2, len(rel_parts))
            ):
                continue
            files.append(f)
    return files


def leftovers(
    repo_root: Path,
    roots: list[str],
    old_prefixes: list[str],
    skip_nested: bool = True,
) -> list[str]:
    pats = [re.escape(p) for p in old_prefixes] + [
        re.escape(p.replace(".", "/")) for p in old_prefixes
    ]
    rx = re.compile(rf"(?:{'|'.join(pats)})(?![\w])")
    out = []
    for f in _scan_files(repo_root, roots, skip_nested):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                out.append(f"{f.relative_to(repo_root)}:{n}: {line.strip()}")
    return out


def _is_empty_pkg(d: Path) -> bool:
    """True when ``d`` holds nothing but empty ``__init__.py`` files and caches."""
    for p in d.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            if p.name != "__init__.py" or p.stat().st_size:
                return False
    return True


def _rewrite_files(repo_root, files, new_to_old, modmap, report) -> None:
    for f in files:
        rel = f.relative_to(repo_root)
        old_rel = new_to_old.get(rel, rel)
        text = f.read_text(encoding="utf-8")
        manual: list[int] = []
        try:
            new = rewrite_source(
                text,
                module_name(old_rel),
                module_name(rel),
                rel.name == "__init__.py",
                modmap,
                manual,
            )
        except SyntaxError as e:
            report.leftovers.append(f"UNPARSEABLE {rel}: {e}")
            continue
        for n in manual:
            report.leftovers.append(
                f"MANUAL {rel}:{n}: {new.splitlines()[n - 1].strip()}"
            )
        if new != text:
            f.write_text(new, encoding="utf-8")
            report.rewritten.append(str(rel))


def apply(mapping_path: Path, repo_root: Path, dry_run: bool) -> Report:
    repo_root = Path(repo_root).resolve()
    roots, moves = load_mapping(mapping_path)
    preflight(moves, repo_root)
    files = expand(moves, repo_root)
    modmap = _modmap(files)
    new_to_old = {d: s for s, d in files.items()}
    report = Report(moved=[(str(s), str(d)) for s, d in files.items()])
    if dry_run:
        for s, d in report.moved:
            print(f"mv {s} -> {d}")
        return report
    for src, dst in files.items():
        (repo_root / dst).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "-C", str(repo_root), "mv", str(src), str(dst)], check=True
        )
    # new package dirs get an empty __init__.py, up to the first existing package
    for dst in {d.parent for d in files.values() if d.suffix == ".py"}:
        missing = []
        for pkg in [dst, *dst.parents]:
            if (repo_root / pkg / "__init__.py").exists():
                for m in missing:
                    (repo_root / m / "__init__.py").write_text("", encoding="utf-8")
                break
            missing.append(pkg)
    # drop source dirs left with nothing but empty __init__.py files
    for src in sorted({s.parent for s in files}, key=lambda p: -len(p.parts)):
        d = repo_root / src
        while d != repo_root and d.is_dir() and _is_empty_pkg(d):
            rel = str(d.relative_to(repo_root))
            subprocess.run(
                ["git", "-C", str(repo_root), "rm", "-rqf", "--ignore-unmatch", rel],
                check=True,
            )
            shutil.rmtree(d, ignore_errors=True)
            d = d.parent
    _rewrite_files(repo_root, _scan_files(repo_root, roots), new_to_old, modmap, report)
    old_prefixes = sorted({k for k in modmap if k not in modmap.values()})
    report.leftovers += leftovers(repo_root, roots, old_prefixes)
    return report


def rewrite_only(mapping_paths, scan: str, repo_root: Path) -> Report:
    """Rewrite imports under ``scan`` for the moves in ``mapping_paths``; moves nothing."""
    repo_root = Path(repo_root).resolve()
    modmap: dict[str, str] = {}
    for mp in mapping_paths:
        for src, dst in load_mapping(Path(mp))[1]:
            if src.suffix in ("", ".py"):
                modmap[module_name(src)] = module_name(dst)
    report = Report()
    files = _scan_files(repo_root, [scan], skip_nested=False)
    _rewrite_files(repo_root, files, {}, modmap, report)
    old_prefixes = sorted({k for k in modmap if k not in modmap.values()})
    report.leftovers += leftovers(repo_root, [scan], old_prefixes, skip_nested=False)
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m harness.reorg_deploy")
    p.add_argument("mapping", nargs="+")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--rewrite-only", action="store_true")
    p.add_argument("--scan", help="directory to rewrite (with --rewrite-only)")
    a = p.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    if a.rewrite_only:
        if not a.scan:
            p.error("--rewrite-only needs --scan <dir>")
        r = rewrite_only(a.mapping, a.scan, repo_root)
    else:
        if len(a.mapping) != 1 or a.scan:
            p.error("move mode takes one mapping and no --scan")
        r = apply(Path(a.mapping[0]), repo_root, a.dry_run)
    print(f"moved {len(r.moved)} files, rewrote {len(r.rewritten)}")
    for line in r.leftovers:
        print(f"LEFTOVER {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
