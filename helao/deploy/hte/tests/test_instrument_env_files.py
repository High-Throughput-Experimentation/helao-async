"""Every instrument's third-party imports are declared in its folder's env files."""

import ast
import re
import sys
from pathlib import Path

from ruamel.yaml import YAML

SERVERS = Path(__file__).resolve().parents[1] / "servers"
# import name -> distribution name, for packages declared under another name
DIST = {"serial": "pyserial", "mecom": "pymecom"}
VENDOR = {"gclib", "pyAndorSDK3", "pyAndorSpectrograph"}  # README only
BASE = set(sys.stdlib_module_names) | {
    "helao",
    "numpy",
    "pandas",
    "scipy",
    "fastapi",
    "pydantic",
    "bokeh",
    "reflex",
    "websockets",
    "httpx",
    "requests",
    "aiofiles",
    "psutil",
    "ruamel",
    "starlette",
    "uvicorn",
    "matplotlib",
    "msgspec",
    "pyzstd",
    "sklearn",
}
HARDWARE = {
    "serial",
    "pyvisa",
    "pylablib",
    "minimalmodbus",
    "nidaqmx",
    "comtypes",
    "mecom",
    "paramiko",
}


def _imports(folder: Path) -> set[str]:
    names = set()
    for f in folder.rglob("*.py"):
        if "tests" in f.parts or "sidecar" in f.parts:
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names.add(node.module.split(".")[0])
    return names


def _dep_names(folder: Path) -> set[str]:
    """Distribution names from environment.yml and requirements.txt only."""
    names = set()
    env = folder / "environment.yml"
    if env.exists():
        deps = YAML(typ="safe").load(env.read_text(encoding="utf-8"))["dependencies"]
        for d in deps:
            for item in d["pip"] if isinstance(d, dict) else [d]:
                names.add(re.split(r"[=<>!~ \[]", item.strip(), maxsplit=1)[0].lower())
    req = folder / "requirements.txt"
    if req.exists():
        for line in req.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].split(";")[0].strip()
            if "://" in line:
                parts = line.split("/")
                names.add(
                    (
                        parts[parts.index("archive") - 1]
                        if "archive" in parts
                        else parts[-1]
                    ).lower()
                )
            elif line:
                names.add(re.split(r"[=<>!~ \[]", line, maxsplit=1)[0].lower())
    return names


def _readme(folder: Path) -> str:
    f = folder / "README.md"
    return f.read_text(encoding="utf-8").lower() if f.exists() else ""


def _folders():
    return sorted(p for p in SERVERS.iterdir() if p.is_dir())


def test_hardware_imports_are_declared():
    missing = []
    for folder in _folders():
        names, readme, imps = _dep_names(folder), _readme(folder), _imports(folder)
        for mod in sorted(imps & HARDWARE):
            if DIST.get(mod, mod).lower() not in names:
                missing.append(f"{folder.name}: {mod}")
        for mod in sorted(imps & VENDOR):
            if mod.lower() not in readme:
                missing.append(f"{folder.name}: {mod}")
    assert not missing, missing


def test_no_undeclared_third_party_imports():
    unknown = [
        f"{f.name}: {m}"
        for f in _folders()
        for m in sorted(_imports(f) - BASE - HARDWARE - VENDOR)
    ]
    assert not unknown, unknown


def test_kinesis_declares_pyft232():
    # pylablib imports ft232 dynamically, so the AST scan cannot see it.
    assert "pyft232" in _dep_names(SERVERS / "kinesis")


def test_environment_files_parse():
    for f in SERVERS.glob("*/environment.yml"):
        data = YAML(typ="safe").load(f.read_text(encoding="utf-8"))
        assert data["dependencies"], f
