"""Compose a host pixi manifest from the tracked base manifest and the env
files of a station's server folders; seed and check the host lock.

Used by helao_env.py. No pixi calls and no helao imports, so every rule is
testable offline. Spec: docs/superpowers/specs/2026-11-11-pixi-env-design.md.
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

#: A URL requirement names no package; map the URL's repo name to the dist
#: name its metadata declares (pixi refuses a mismatch).
URL_DIST_NAMES = {"pyMeCom": "mecom"}

_CUDA_BUILD = re.compile(r"^cuda(1\d)(\d)")
_WIN_MARKER = re.compile(r"""sys_platform\s*(==|!=)\s*['"]win32['"]""")
_NAME = re.compile(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*(.*)$")


class ComposeError(Exception):
    """An env file pixi cannot express, or two folders that disagree."""


def _yaml():
    from ruamel.yaml import YAML

    return YAML(typ="safe")


def conda_spec(line: str) -> tuple[str, str | dict]:
    """(name, pixi spec) for one conda dependency string."""
    s = line.strip().split("::")[-1]
    m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(.*)$", s)
    if not m:
        raise ComposeError(f"cannot read conda spec {line!r}")
    name, rest = m.group(1), m.group(2).strip()
    if not rest:
        return name, "*"
    if rest.startswith("=") and not rest.startswith("=="):
        version, _, build = rest[1:].partition("=")
        if "*" not in version:
            version += ".*"
        return name, ({"version": version, "build": build} if build else version)
    return name, rest


def _extras(bracket: str | None) -> list[str]:
    return [e.strip() for e in bracket[1:-1].split(",") if e.strip()] if bracket else []


def pypi_spec(line: str) -> tuple[str, str | dict, str | None] | None:
    """(name, pixi spec, marker) for one requirements.txt line; None if blank."""
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    s = s.split(" #", 1)[0].strip()
    if s.startswith("-"):
        raise ComposeError(f"requirements option {s!r} is not supported")
    marker = None
    if ";" in s:
        s, marker = (x.strip() for x in s.split(";", 1))
    if s.startswith(("http://", "https://")):
        parts = s.rstrip("/").split("/")
        name = URL_DIST_NAMES.get(parts[-3]) if len(parts) >= 3 else None
        if name is None:
            raise ComposeError(
                f"URL requirement {s!r}: add its dist name to URL_DIST_NAMES"
            )
        return name, {"url": s}, marker
    if " @ " in s:
        req, url = (x.strip() for x in s.split(" @ ", 1))
        m = _NAME.match(req)
        if not m:
            raise ComposeError(f"cannot read requirement {line!r}")
        spec: dict = {"git": url[4:]} if url.startswith("git+") else {"url": url}
        if m.group(2):
            spec["extras"] = _extras(m.group(2))
        return m.group(1), spec, marker
    m = _NAME.match(s)
    if not m:
        raise ComposeError(f"cannot read requirement {line!r}")
    name, ver = m.group(1), m.group(3).strip() or "*"
    if m.group(2):
        return name, {"version": ver, "extras": _extras(m.group(2))}, marker
    return name, ver, marker


def _cuda_of(spec) -> str | None:
    if isinstance(spec, dict):
        m = _CUDA_BUILD.match(str(spec.get("build", "")))
        if m:
            return f"{m.group(1)}.{m.group(2)}"
    return None


def _stderr(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def compose(
    base: dict,
    folders,
    platform: str,
    repo_root: Path,
    states_files=(),
    pip_env_for=None,
    warn=None,
) -> dict:
    """Host manifest: ``base`` for ``platform`` only, plus every folder's
    root env files merged into the default environment.

    ``pip_env_for(folder) -> {VAR: template}`` supplies a folder's pip_env
    overrides (``{prefix}``/``{PATH}`` templates); ``warn(msg)`` reports a
    folder overriding a base spec.
    """
    warn = warn or _stderr
    win = platform.startswith("win")
    var = (lambda n: f"%{n}%") if win else (lambda n: f"${n}")
    m = copy.deepcopy(base)
    here = (m.pop("target", None) or {}).get(platform, {})
    deps = {**m.get("dependencies", {}), **here.get("dependencies", {})}
    pypi = {**m.get("pypi-dependencies", {}), **here.get("pypi-dependencies", {})}
    act = {
        **m.get("activation", {}).get("env", {}),
        **here.get("activation", {}).get("env", {}),
    }
    owners: dict[tuple[str, str], tuple[Path, object]] = {}

    def add(table: dict, kind: str, name: str, spec, folder: Path) -> None:
        key = (kind, name.lower())
        if key in owners:
            prev_folder, prev = owners[key]
            if prev != spec:
                raise ComposeError(
                    f"{name}: {prev_folder} wants {prev!r} but {folder} wants {spec!r}"
                )
            return
        owners[key] = (folder, spec)
        if name in table and table[name] != spec:
            warn(f"{folder} overrides base {name} {table[name]!r} with {spec!r}")
        table[name] = spec

    def add_pypi(line: str, folder: Path) -> None:
        parsed = pypi_spec(line)
        if parsed is None:
            return
        name, spec, marker = parsed
        if marker is not None:
            mk = _WIN_MARKER.fullmatch(marker)
            if not mk:
                raise ComposeError(
                    f"{folder}: marker {marker!r} is not supported "
                    '(only sys_platform == / != "win32")'
                )
            if (mk.group(1) == "==") != win:
                return
        add(pypi, "pypi", name, spec, folder)

    for folder in sorted(Path(f) for f in folders):
        for fname in ("environment.yml", f"environment_{platform}.yml"):
            f = folder / fname
            if not f.is_file():
                continue
            data = _yaml().load(f.read_text(encoding="utf-8")) or {}
            for d in data.get("dependencies") or []:
                if isinstance(d, dict):
                    for line in d.get("pip") or []:
                        add_pypi(str(line), folder)
                else:
                    add(deps, "conda", *conda_spec(str(d)), folder)
        req = folder / "requirements.txt"
        if req.is_file():
            for line in req.read_text(encoding="utf-8").splitlines():
                add_pypi(line, folder)
        for k, v in (pip_env_for(folder) or {} if pip_env_for else {}).items():
            v = v.replace("{prefix}", var("CONDA_PREFIX")).replace(
                "{PATH}", var("PATH")
            )
            key = ("env", k)
            if key in owners and owners[key][1] != v:
                raise ComposeError(
                    f"{k}: {owners[key][0]} sets {owners[key][1]!r} but {folder} sets {v!r}"
                )
            owners[key] = (folder, v)
            act[k] = v

    if "pytorch-cpu" in deps and _cuda_of(deps.get("pytorch")):
        del deps["pytorch-cpu"]  # CUDA pytorch overrides pytorch-cpu
    cudas = {c for c in map(_cuda_of, deps.values()) if c}
    if len(cudas) > 1:
        raise ComposeError(f"conflicting CUDA builds: {sorted(cudas)}")
    m["workspace"]["platforms"] = (
        [{"name": f"{platform}-cuda", "platform": platform, "cuda": cudas.pop()}]
        if cudas
        else [platform]
    )
    act["PYTHONPATH"] = str(repo_root)
    act["HELAOLAUNCH"] = str(Path(repo_root) / ("helao.bat" if win else "helao.sh"))
    act["HELAO_STATION_PREFIXES"] = (";" if win else ":").join(
        sorted(str(p) for p in states_files)
    )
    m["dependencies"] = deps
    m["pypi-dependencies"] = pypi
    m.setdefault("activation", {})["env"] = act
    return m


def platform_key(manifest: dict) -> str:
    """Lock platform key of a composed manifest's single platform."""
    (entry,) = manifest["workspace"]["platforms"]
    return entry["name"] if isinstance(entry, dict) else entry
