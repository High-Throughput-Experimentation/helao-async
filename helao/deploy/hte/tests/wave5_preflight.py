"""Wave-5 preflight validator for hte framework cut-over configs.

Statically validates one (or all) hte station config(s) the SAME way the
launchers do, WITHOUT starting any server or touching hardware. Run this on a
station before a live Wave-5 launch to catch config/resolution errors offline.

What it checks, per config:
  1. Loads the config by FULL PATH (avoids the bare-prefix glob collision noted
     for ``icpm1`` — a private deployment also ships ``icpm1.yml``).
  2. ``launch.validateConfig`` parity: required keys (host/port/group), host is
     str, port is int, group is str, exactly one of fast/bokeh, unique server
     keys, unique host:port.
  3. Per server, resolves the app module import path EXACTLY as
     ``fast_launcher`` / ``bokeh_launcher`` do (deployment auto-detect +
     ``deployment: framework`` override) and confirms the module imports and
     exposes the right factory (``makeApp`` / ``makeBokehApp``).
  4. Classifies failures: import errors that name a known Windows/hardware-only
     dependency (gclib, comtypes, nidaqmx, minimalmodbus, pyAndorSDK3, pywin32,
     pythonnet/clr) are reported as WINDOWS-DEFERRED (expected on Linux/CI, must
     be re-run on the station) rather than hard failures.
  5. Reports remote hosts (host not loopback / not this machine) — their action
     modules cannot be import-checked here; do that ON the remote host.

Usage (run with the helao conda env python):
    python helao/deploy/hte/tests/wave5_preflight.py <config.yml>      # one station
    python helao/deploy/hte/tests/wave5_preflight.py --all             # every hte config
    python helao/deploy/hte/tests/wave5_preflight.py --all --strict    # WINDOWS-DEFERRED => failure

Exit code: 0 = all checks pass (deferred allowed unless --strict), 1 = any failure.
This is offline static validation. It does NOT replace the on-station hardware
smoke checklist (see wave5_runbook.md).
"""

__all__ = []

import os
import sys
import socket
import importlib
import traceback
from glob import glob

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Top-level module names that only exist on a Windows station / behind hardware.
# An import error naming one of these is EXPECTED off-station, not a config bug.
WINDOWS_ONLY_DEPS = {
    "gclib",          # Galil motion/io
    "comtypes",       # Gamry pstat
    "nidaqmx",        # NI DAQ
    "minimalmodbus",  # MFC / modbus instruments
    "pyAndorSDK3",    # Andor spectrometer
    "clr",            # pythonnet
    "win32com",
    "win32api",
    "pywintypes",
    "pythoncom",
}

CODE_KEYS = ("fast", "bokeh")
REQ_KEYS = ("host", "port", "group")


class Result:
    """Per-server check outcome."""

    OK = "OK"
    FAIL = "FAIL"
    DEFERRED = "WINDOWS-DEFERRED"
    REMOTE = "REMOTE-SKIP"

    def __init__(self, server, status, detail, module=None):
        self.server = server
        self.status = status
        self.detail = detail
        self.module = module


def _resolve_module_path(deployment, group, name):
    """Mirror fast_launcher/bokeh_launcher.resolve_app_module_path."""
    if deployment == "framework":
        return f"helao.framework.app.servers.{name}"
    return f"helao.deploy.{deployment}.servers.{group}.{name}"


def _auto_detect_deployment(config_path, group, name):
    """Mirror the launcher glob auto-detect when no per-server deployment key."""
    deploy_root = os.path.dirname(os.path.dirname(os.path.dirname(config_path)))
    candidates = glob(
        os.path.join(deploy_root, "*", "servers", group, f"{name}.py")
    )
    if len(candidates) == 1:
        return os.path.basename(
            os.path.dirname(os.path.dirname(os.path.dirname(candidates[0])))
        )
    if len(candidates) > 1:
        # launcher prefers the deployment matching the config path
        same = [
            c for c in candidates
            if c.startswith(os.path.dirname(os.path.dirname(config_path)))
        ]
        chosen = same[0] if same else candidates[0]
        return os.path.basename(
            os.path.dirname(os.path.dirname(os.path.dirname(chosen)))
        )
    raise FileNotFoundError(
        f"no '{name}.py' found under any deploy/*/servers/{group}/ for server"
    )


def _is_local(host):
    """Best-effort: is `host` this machine (so its module can be import-checked)?"""
    if host in ("127.0.0.1", "0.0.0.0", "localhost", "::1"):
        return True
    try:
        local_names = {socket.gethostname(), socket.getfqdn()}
        if host in local_names:
            return True
        # resolve host -> ip and compare with our addrs
        host_ip = socket.gethostbyname(host)
        if host_ip.startswith("127."):
            return True
        my_ips = {
            ai[4][0] for ai in socket.getaddrinfo(socket.gethostname(), None)
        }
        return host_ip in my_ips
    except Exception:
        return False


def _classify_import_error(exc):
    """Return the offending Windows-only dep name, or None if it's a real error."""
    # Walk the exception chain for a ModuleNotFoundError naming a known dep.
    seen = exc
    while seen is not None:
        name = getattr(seen, "name", None)
        if name:
            top = name.split(".")[0]
            if top in WINDOWS_ONLY_DEPS:
                return top
        # also scan the message text (some drivers re-raise as plain ImportError)
        msg = str(seen)
        for dep in WINDOWS_ONLY_DEPS:
            if dep in msg:
                return dep
        seen = seen.__cause__ or seen.__context__
    return None


def validate_structure(config):
    """launch.validateConfig parity. Returns list of error strings (empty = ok)."""
    errors = []
    servers = config.get("servers")
    if not servers:
        return ["'servers' key missing or empty"]
    if len(servers) != len(set(servers)):
        errors.append("server keys are not unique")
    addrs = []
    for name, sd in servers.items():
        missing = [k for k in REQ_KEYS if k not in sd]
        if missing:
            errors.append(f"{name}: missing required keys {missing}")
            continue
        if not isinstance(sd["host"], str):
            errors.append(f"{name}: 'host' is not a string")
        if not isinstance(sd["port"], int):
            errors.append(f"{name}: 'port' is not an integer")
        if not isinstance(sd["group"], str):
            errors.append(f"{name}: 'group' is not a string")
        code = [k for k in sd if k in CODE_KEYS]
        if len(code) > 1:
            errors.append(f"{name}: more than one code key {code}")
        elif len(code) == 1 and not isinstance(sd[code[0]], str):
            errors.append(f"{name}: '{code[0]}' is not a string")
        addrs.append(f"{sd['host']}:{sd['port']}")
    if len(addrs) != len(set(addrs)):
        dupes = sorted({a for a in addrs if addrs.count(a) > 1})
        errors.append(f"duplicate host:port: {dupes}")
    return errors


def check_server(name, sd, config_path):
    """Resolve + import one server's app module; return a Result."""
    group = sd.get("group")
    code = [k for k in sd if k in CODE_KEYS]
    if not code:
        return Result(name, Result.OK, f"{group}: no code key (externally managed)")
    code_key = code[0]
    mod_name = sd[code_key]
    factory = "makeApp" if code_key == "fast" else "makeBokehApp"

    explicit = sd.get("deployment")
    try:
        if explicit:
            deployment = explicit
        else:
            deployment = _auto_detect_deployment(config_path, group, mod_name)
    except Exception as exc:
        return Result(name, Result.FAIL, f"deployment resolution failed: {exc}")

    module_path = _resolve_module_path(deployment, group, mod_name)

    # Remote action servers: their drivers live on the remote host; importing the
    # module here would pull hardware deps that aren't installed locally. Skip,
    # but still confirm the resolved module path for non-remote framework hosts.
    host = sd.get("host", "")
    framework_host = deployment == "framework"
    if not framework_host and not _is_local(host):
        return Result(
            name, Result.REMOTE,
            f"{module_path} -> import-check on host '{host}'", module_path,
        )

    try:
        mod = importlib.import_module(module_path)
    except Exception as exc:
        dep = _classify_import_error(exc)
        if dep:
            return Result(
                name, Result.DEFERRED,
                f"{module_path}: needs '{dep}' (Windows/hardware) — verify on station",
                module_path,
            )
        tb = traceback.format_exc().strip().splitlines()[-1]
        return Result(name, Result.FAIL, f"{module_path}: import error: {tb}", module_path)

    if not hasattr(mod, factory):
        return Result(
            name, Result.FAIL,
            f"{module_path}: missing factory '{factory}'", module_path,
        )
    return Result(name, Result.OK, f"{module_path}.{factory}", module_path)


def preflight_config(config_path, strict=False):
    """Run all checks for one config. Returns (passed: bool, results: list)."""
    from helao.helpers.config_loader import read_config

    print(f"\n{'=' * 78}\nCONFIG: {config_path}\n{'=' * 78}")
    try:
        config = read_config(config_path)
    except Exception as exc:
        print(f"  [FAIL] could not load config: {exc}")
        return False, []

    struct_errors = validate_structure(config)
    if struct_errors:
        print("  STRUCTURE:")
        for e in struct_errors:
            print(f"    [FAIL] {e}")
    else:
        print("  STRUCTURE: [OK] validateConfig parity passed")

    detected = os.path.basename(
        os.path.dirname(os.path.dirname(config.get("loaded_config_path", config_path)))
    )
    print(f"  deployment (config path): {detected}")
    print(f"  dummy={config.get('dummy')}  simulation={config.get('simulation')}")

    results = []
    servers = config.get("servers", {})
    width = max((len(s) for s in servers), default=4)
    for name, sd in servers.items():
        res = check_server(name, sd, config.get("loaded_config_path", config_path))
        results.append(res)
        tag = {
            Result.OK: "[ OK ]",
            Result.FAIL: "[FAIL]",
            Result.DEFERRED: "[DEFR]",
            Result.REMOTE: "[RMT ]",
        }[res.status]
        grp = sd.get("group", "?")
        print(f"  {tag} {name:<{width}}  {grp:<12} {res.detail}")

    has_fail = bool(struct_errors) or any(r.status == Result.FAIL for r in results)
    has_defer = any(r.status == Result.DEFERRED for r in results)
    has_remote = any(r.status == Result.REMOTE for r in results)
    if has_defer:
        print("  NOTE: WINDOWS-DEFERRED servers MUST be import-checked on the station.")
    if has_remote:
        print("  NOTE: REMOTE servers MUST be import-checked on their own host.")

    passed = not has_fail and not (strict and has_defer)
    return passed, results


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    strict = "--strict" in flags

    if "--all" in flags:
        cfg_dir = os.path.join(
            REPO_ROOT, "helao", "deploy", "hte", "configs"
        )
        targets = sorted(glob(os.path.join(cfg_dir, "*.yml")))
    elif args:
        targets = [os.path.abspath(a) for a in args]
    else:
        print(__doc__)
        return 1

    overall_ok = True
    summary = []
    for cfg in targets:
        ok, _ = preflight_config(cfg, strict=strict)
        overall_ok = overall_ok and ok
        summary.append((os.path.basename(cfg), ok))

    print(f"\n{'=' * 78}\nSUMMARY ({'strict' if strict else 'lenient'})\n{'=' * 78}")
    for name, ok in summary:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n{'ALL PASS' if overall_ok else 'FAILURES PRESENT'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
