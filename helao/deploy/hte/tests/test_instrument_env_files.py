"""Every instrument's third-party imports are declared in its folder's env files."""

import ast
import sys
from pathlib import Path

from ruamel.yaml import YAML

SERVERS = Path(__file__).resolve().parents[1] / "servers"
# import name -> distribution name, for packages declared under another name
DIST = {"serial": "pyserial", "mecom": "pymecom", "minimalmodbus": "minimalmodbus"}
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


def _declared(folder: Path) -> str:
    text = ""
    for name in ("environment.yml", "requirements.txt", "README.md"):
        if (folder / name).exists():
            text += (folder / name).read_text(encoding="utf-8").lower()
    return text


def test_hardware_imports_are_declared():
    missing = []
    for folder in sorted(p for p in SERVERS.iterdir() if p.is_dir()):
        declared = _declared(folder)
        for mod in sorted(_imports(folder) & (HARDWARE | VENDOR)):
            if DIST.get(mod, mod).lower() not in declared:
                missing.append(f"{folder.name}: {mod}")
    assert not missing, missing


def test_environment_files_parse():
    for f in SERVERS.glob("*/environment.yml"):
        data = YAML(typ="safe").load(f.read_text(encoding="utf-8"))
        assert data["dependencies"], f
