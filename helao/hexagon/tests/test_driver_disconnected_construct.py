"""Disconnected construction is a ratchet, and the host connects drivers at startup.

A ``HelaoDriver`` must not do device I/O in ``__init__``. Nine hte drivers still
do (``CONSTRUCTOR_CONNECT_PENDING``); each increment of the hardware wiring moves
its classes out of that set and into ``CONNECT_ON_STARTUP``, so forgetting either
half goes red. The pending set is checked by AST (a ``connect`` call on ``self``
inside ``__init__``), which also covers a class whose module cannot be imported
here. A runtime tripwire judges the other direction: every importable class not in
the pending set constructs with zero recorded vendor/I/O hits.

The tripwire records instead of only raising, because most ``connect()`` bodies
swallow exceptions. Keys are ``<module>.<qualname>`` relative to
``helao.deploy.hte.drivers`` or ``helao.hexagon.adapters.native`` (two classes are
named ``Galil``). Nothing here writes outside ``tmp_path``.
"""

import ast
import copy
import ctypes
import importlib
import inspect
import re
import socket
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Final, Optional

import pytest
import yaml

from helao.core.drivers.helao_driver import HelaoDriver

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DRIVER_ROOTS: Final[tuple[str, ...]] = (
    "helao/deploy/hte/drivers",
    "helao/hexagon/adapters/native",
)
# Skipped from import (reason below); leancat's driver stays in the AST scan.
# `logger/__init__.py` imports a `main_log` that `logger.py` does not define, an
# in-tree ImportError that cascades to script/commands/database/station; the
# subtree also needs `tenacity` and `opcua`, which are not installed. Fixing the
# package is out of scope (follow-up F2).
IMPORT_ALLOWLIST: Final[tuple[str, ...]] = ("test_station/leancat/",)

# Drivers whose __init__ still connects, keyed by module.qualname.
CONSTRUCTOR_CONNECT_PENDING: Final[frozenset[str]] = frozenset(
    {
        "mfc.alicat_driver.AliCatMFC",  # I4
        "motion.kinesis_driver.KinesisMotor",  # I5
        "pstat.gamry.driver.GamryDriver",  # I7
        "pump.legato_driver.KDS100",  # I3
        "pump.simdos_driver.SIMDOS",  # I3
        # no hte station; not flipped by this plan, see amendment 3
        "test_station.leancat.driver.LeancatDriver",
    }
)
# Drivers whose connect_on_startup is True (the host connects them).
CONNECT_ON_STARTUP: Final[frozenset[str]] = frozenset(
    {
        "sensor.cm0134_driver.CM0134",  # I1
        "sensor.sprintir_driver.SprintIR",  # I1
        "temperature_control.mecom_driver.MeerstetterTEC",  # I2
    }
)

# Settled overrides: a config the constructor rejects without these keys.
OVERRIDES: Final[dict[str, dict]] = {
    # no hte config in any repo; the constructor indexes these two keys
    "MeerstetterTEC": {"channel": 1, "port": "tec_port"},
    # the constructor builds its URL from sidecar_port; port 1 is never contacted
    "XafsSidecarDriver": {"sidecar_port": 1},
}
VENDOR_NAMES: Final[tuple[str, ...]] = (
    "serial",
    "Serial",
    "Thorlabs",
    "MeCom",
    "nidaqmx",
    "minimalmodbus",
    "gclib",
    "comtypes",
    "pylablib",
)
VENDOR_PACKAGES: Final[tuple[str, ...]] = (
    "gclib",
    "comtypes",
    "comtypes.client",
    "minimalmodbus",
    "nidaqmx",
    "leancat_helao",
    "pylablib",
)


class TripwireHit(BaseException):
    pass


def _module_files() -> list[Path]:
    out = []
    for root in DRIVER_ROOTS:
        for p in sorted((REPO_ROOT / root).rglob("*.py")):
            rel = p.relative_to(REPO_ROOT).as_posix()
            if (
                "__pycache__" in p.parts
                or "/tests/" in rel
                or p.name.startswith("test_")
            ):
                continue
            if any(a in rel for a in IMPORT_ALLOWLIST):
                continue
            out.append(p)
    return out


def _modname(p: Path) -> str:
    mod = p.relative_to(REPO_ROOT).with_suffix("").as_posix().replace("/", ".")
    return mod[: -len(".__init__")] if mod.endswith(".__init__") else mod


def _key(module: str, qualname: str) -> str:
    for prefix in ("helao.deploy.hte.drivers.", "helao.hexagon.adapters.native."):
        if module.startswith(prefix):
            return f"{module[len(prefix):]}.{qualname}"
    return f"{module}.{qualname}"


def constructor_connect_keys() -> set[str]:
    """AST scan: every HelaoDriver subclass whose ``__init__`` calls ``self...connect``."""
    classes = []
    for root in DRIVER_ROOTS:
        for p in sorted((REPO_ROOT / root).rglob("*.py")):
            if "__pycache__" in p.parts or "/tests/" in p.as_posix():
                continue
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(n, ast.ClassDef):
                    bases = [ast.unparse(b).split(".")[-1] for b in n.bases]
                    classes.append((bases, n, p))
    known = {"HelaoDriver"}
    scope: dict[int, tuple[ast.ClassDef, Path]] = {}
    changed = True
    while changed:
        changed = False
        for bases, node, p in classes:
            if id(node) not in scope and any(b in known for b in bases):
                scope[id(node)] = (node, p)
                known.add(node.name)
                changed = True
    found = set()
    for node, p in scope.values():
        for f in node.body:
            if not (isinstance(f, ast.FunctionDef) and f.name == "__init__"):
                continue
            for n in ast.walk(f):
                if (
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "connect"
                ):
                    root = n.func.value
                    while isinstance(root, ast.Attribute):
                        root = root.value
                    if isinstance(root, ast.Name) and root.id == "self":
                        found.add(_key(_modname(p), node.name))
    return found


class _Sentinel(types.ModuleType):
    def __init__(self, name: str, hits: list, current: list):
        super().__init__(name)
        self._hits, self._current = hits, current

    def __getattr__(self, n: str) -> Any:
        if n.startswith("__"):
            raise AttributeError(n)
        self._hits.append((f"sentinel:{self.__name__}.{n}", self._current[0]))
        raise TripwireHit(self.__name__)


class Armed:
    """The installed tripwire: ``classify(cls, config) -> (what-hits, exception)``."""

    def __init__(self, modules: dict[str, types.ModuleType], patch_names: bool = True):
        self.hits: list[tuple[str, Optional[str]]] = []
        self.current: list[Optional[str]] = [None]
        self.mp = pytest.MonkeyPatch()
        self._install(modules, patch_names)

    def _tw(self, what: str):
        def f(*a: Any, **k: Any) -> Any:
            self.hits.append((what, self.current[0]))
            raise TripwireHit(what)

        return f

    def _install(self, modules: dict[str, types.ModuleType], patch_names: bool) -> None:
        mp = self.mp
        mp.setattr(socket.socket, "connect", self._tw("socket.connect"))
        mp.setattr(subprocess, "Popen", self._tw("subprocess.Popen"))
        mp.setattr(ctypes, "CDLL", self._tw("ctypes.CDLL"))
        if hasattr(ctypes, "WinDLL"):
            mp.setattr(ctypes, "WinDLL", self._tw("ctypes.WinDLL"))
        try:
            import serial

            mp.setattr(serial, "Serial", self._tw("serial.Serial"))
        except ImportError:
            pass
        for pkg in VENDOR_PACKAGES:
            mp.setitem(sys.modules, pkg, _Sentinel(pkg, self.hits, self.current))
        if not patch_names:
            return
        # module-level bound vendor names: a sys.modules sentinel cannot reach them.
        # Never patch exception classes; they appear in `except` clauses.
        for modname, mod in modules.items():
            for name, obj in list(vars(mod).items()):
                if inspect.isclass(obj) and issubclass(obj, BaseException):
                    continue
                top = (
                    getattr(obj, "__module__", None)
                    or getattr(obj, "__name__", "")
                    or ""
                ).split(".")[0]
                if name not in VENDOR_NAMES and top not in VENDOR_NAMES:
                    continue
                if isinstance(obj, types.ModuleType):
                    mp.setattr(
                        mod,
                        name,
                        _Sentinel(obj.__name__, self.hits, self.current),
                    )
                elif callable(obj):
                    mp.setattr(mod, name, self._tw(f"{modname}.{name}"))

    def classify(
        self, cls: type, config: dict
    ) -> tuple[list[str], Optional[BaseException]]:
        start = len(self.hits)
        self.current[0] = cls.__qualname__
        exc: Optional[BaseException] = None
        try:
            cls(config=config)
        except TripwireHit:
            pass
        except Exception as e:
            exc = e
        finally:
            self.current[0] = None
        return [h[0] for h in self.hits[start:]], exc

    def undo(self) -> None:
        self.mp.undo()


def _hte_configs() -> list[dict]:
    out = []
    for y in sorted((REPO_ROOT / "helao/deploy/hte/configs").glob("*.yml")):
        try:
            out.append(yaml.safe_load(y.read_text(encoding="utf-8")) or {})
        except yaml.YAMLError:
            continue
    return out


def _sanitise(d: Any, tmp: Path) -> Any:
    if isinstance(d, dict):
        return {k: _sanitise(v, tmp) for k, v in d.items()}
    if isinstance(d, list):
        return [_sanitise(v, tmp) for v in d]
    if isinstance(d, str) and (":\\" in d or d.startswith("/")):
        return str(tmp / re.sub(r"[^A-Za-z0-9_]", "_", d))
    return d


def config_for(cls: type, tmp: Path, configs: list[dict]) -> dict:
    """Minimal config: the first hte config whose server hosts ``cls``, else ``{}``."""
    name = cls.__name__
    cfg: dict = {}
    for p in (REPO_ROOT / "helao/deploy/hte/servers/action").glob("*.py"):
        if re.search(
            rf"\b{name}\(|driver_classes=\[{name}\b", p.read_text(encoding="utf-8")
        ):
            for c in configs:
                for v in (c.get("servers") or {}).values():
                    if v.get("fast") == p.stem and isinstance(v.get("params"), dict):
                        cfg = _sanitise(copy.deepcopy(v["params"]), tmp)
                        break
                if cfg:
                    break
            if cfg:
                break
    extra = {
        k: (str(tmp / v) if isinstance(v, str) and k == "port" else v)
        for k, v in OVERRIDES.get(name, {}).items()
    }
    return {**cfg, **extra}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    snapshot = set(p.name for p in REPO_ROOT.iterdir())
    tmp = tmp_path_factory.mktemp("construct")
    modules: dict[str, types.ModuleType] = {}
    env_skipped: dict[str, str] = {}
    failures: dict[str, str] = {}
    for p in _module_files():
        name = _modname(p)
        try:
            modules[name] = importlib.import_module(name)
        except ImportError as e:
            top = (getattr(e, "name", None) or "").split(".")[0]
            if top and top != "helao":
                env_skipped[name] = f"{type(e).__name__}: {e}"  # run_tests.py's ENV
            else:
                failures[name] = f"{type(e).__name__}: {e}"
        except Exception as e:
            failures[name] = f"{type(e).__name__}: {e}"
    classes: dict[str, type] = {}
    for modname, mod in modules.items():
        for n, c in vars(mod).items():
            if (
                inspect.isclass(c)
                and issubclass(c, HelaoDriver)
                and c is not HelaoDriver
                and c.__module__ == modname
                and not inspect.isabstract(c)
            ):
                classes[_key(modname, c.__qualname__)] = c
    configs = _hte_configs()
    armed = Armed(modules)
    results = {}
    try:
        for key, c in sorted(classes.items()):
            results[key] = armed.classify(c, config_for(c, tmp, configs))
    finally:
        pass
    yield types.SimpleNamespace(
        armed=armed,
        classes=classes,
        results=results,
        failures=failures,
        env_skipped=env_skipped,
        tmp=tmp,
        modules=modules,
        snapshot=snapshot,
    )
    armed.undo()


def test_every_module_imports(world) -> None:
    assert not world.failures, world.failures


def test_pending_set_matches_the_constructor_scan() -> None:
    found = constructor_connect_keys()
    for key in sorted(CONSTRUCTOR_CONNECT_PENDING - found):
        pytest.fail(
            f"{key} no longer connects in __init__: remove it from "
            "CONSTRUCTOR_CONNECT_PENDING"
        )
    assert (
        found == CONSTRUCTOR_CONNECT_PENDING
    ), f"connects in __init__ but not listed: {sorted(found - CONSTRUCTOR_CONNECT_PENDING)}"


def test_construct_is_disconnected(world) -> None:
    bad = {
        k: r
        for k, r in world.results.items()
        if k not in CONSTRUCTOR_CONNECT_PENDING and (r[0] or r[1] is not None)
    }
    assert not bad, bad


def test_pending_importable_drivers_do_hit(world) -> None:
    importable = {k for k in CONSTRUCTOR_CONNECT_PENDING if k in world.results}
    assert importable, "no pending driver was importable: the tripwire proves nothing"
    silent = sorted(k for k in importable if not world.results[k][0])
    assert not silent, f"tripwire saw nothing for {silent}"


def test_only_leancat_is_not_importable(world) -> None:
    missing = CONSTRUCTOR_CONNECT_PENDING - set(world.results)
    assert missing == {"test_station.leancat.driver.LeancatDriver"}


def test_connect_on_startup_set_is_exact(world) -> None:
    flagged = {k for k, c in world.classes.items() if c.connect_on_startup}
    assert flagged == CONNECT_ON_STARTUP


def test_nothing_written_outside_tmp(world) -> None:
    assert {p.name for p in REPO_ROOT.iterdir()} == world.snapshot


def test_classify_sees_a_constructor_connect(world) -> None:
    from helao.deploy.hte.drivers.spec.spectral_products_driver import SM303

    lib = world.tmp / "fake_lib.so"
    lib.write_bytes(b"")

    class _Mut(SM303):
        def __init__(self, config: dict = {}):
            super().__init__(config=config)
            self.connect()

    cfg = {**config_for(SM303, world.tmp, _hte_configs()), "lib_path": str(lib)}
    hits, _ = world.armed.classify(_Mut, cfg)
    assert "ctypes.CDLL" in hits
