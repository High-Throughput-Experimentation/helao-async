"""Report -- and optionally remove -- the Windows 260-character path ceiling.

A station's run tree is deep by construction:
``<root>/RUNS_ACTIVE/<week>/<day>/<sequence>/<experiment>/<action>/<file>``,
where the sequence and experiment components carry the library function's own
name. On 2026-09-09 an ECMS action reached 232 characters for its ``-act.yml``
and the write failed anyway, because the atomic-write staging name was longer
than the file it staged. That specific tax is gone (see
:func:`helao.helpers.file_utils.staging_path`), but it only bought headroom --
roughly 26 characters remained before the *final* path breached ``MAX_PATH``,
and a longer experiment name would have broken the real write instead.

Removing the ceiling is an operating-system setting, not a code change, and
that is deliberate. Prefixing paths with ``\\\\?\\`` at HELAO's own call sites
would cover perhaps thirty writers while leaving every read, every glob, and
every third-party library that touches the run tree -- ``boto3`` streaming a
file to S3, ``zipfile`` building a sequence archive, ``ruamel`` loading a yml,
a vendor SDK appending to an ``.mpr`` inside the action directory -- still
capped. Worse, a ``\\\\?\\``-prefixed path that escapes into recorded metadata
(``FileInfo.file_name``, an S3 key, a yml value) is a data defect that outlives
the run. Two settings make the cap disappear for the whole process, libraries
included:

1. ``HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem\\LongPathsEnabled``
   set to DWORD ``1`` (Windows 10 1607 / Server 2016 and later). Needs
   administrator rights, and a reboot to be safe -- the value is read as a
   process starts.
2. The executable must declare ``longPathAware`` in its manifest. CPython has
   since 3.6, so a stock ``python.exe`` already qualifies. This is worth
   knowing only because it is the half that explains a machine where the
   registry reads ``1`` and long paths still do not work.

**The registry value is evidence; the probe is proof.** This module reports
both, and the exit status follows the probe. It creates one directory level at
a time under ``<root>/STATES`` so that a failure reports the *measured* ceiling
rather than just "failed", then unwinds everything it made. Nothing outside its
own probe directory is read, written, or removed, and the probe directory is
under ``STATES`` rather than a ``RUNS_*`` tree precisely so a syncer sweep
running at the same time cannot see it.

Usage::

    python -m helao.core.tests.check_long_paths <root>
    python -m helao.core.tests.check_long_paths C:\\INST_hlo\\DATA
    python -m helao.core.tests.check_long_paths C:\\INST_hlo\\DATA --enable

``--enable`` sets the registry value and is the only thing here that writes
outside the probe directory. It must be run from an elevated prompt; without
administrator rights it reports the failure rather than pretending to succeed.
Reboot afterwards, then re-run without ``--enable`` to confirm.

Exit status is 0 when a path longer than ``--target`` (default 300) can be
created, written, renamed onto, read back, listed, and removed. It is 1 when
the ceiling is still in place, and 1 when the probe could not run at all -- an
unusable root must not read as a clean result.
"""

__all__ = [
    "LONG_PATH_REGISTRY_KEY",
    "LONG_PATH_REGISTRY_VALUE",
    "ProbeResult",
    "enable_long_paths",
    "main",
    "probe_root",
    "registry_long_paths_enabled",
]

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

LONG_PATH_REGISTRY_KEY = r"SYSTEM\CurrentControlSet\Control\FileSystem"
LONG_PATH_REGISTRY_VALUE = "LongPathsEnabled"

# One probe directory component. Kept well under the 255-character per-component
# limit that survives independently of MAX_PATH, so the only thing the probe can
# ever measure is the *total* path length.
_COMPONENT = "helao_longpath_probe_padding_component"
_PROBE_DIRNAME = ".helao_longpath_probe"


@dataclass
class ProbeResult:
    """Outcome of an empirical long-path probe against one root.

    Attributes:
        target: Path length the probe was asked to exceed.
        reached: Longest full file path that was successfully written and read
            back. ``0`` when even the probe directory could not be created.
        ok: Whether ``reached`` met or exceeded ``target``.
        error: Description of the first failure, or ``None``.
        cleaned: Whether the probe removed everything it created.
        leftover: Paths the probe created but could not remove.
    """

    target: int
    reached: int = 0
    ok: bool = False
    error: Optional[str] = None
    cleaned: bool = True
    leftover: list[str] = field(default_factory=list)


def registry_long_paths_enabled() -> Optional[bool]:
    """Return the ``LongPathsEnabled`` registry value as a bool.

    Returns:
        ``True``/``False`` for a readable value, or ``None`` when the platform
        is not Windows or the value cannot be read (missing key, or a
        permission error). ``None`` is not a failure -- the probe, not this,
        decides whether the ceiling is present.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg  # noqa: PLC0415 -- Windows-only, imported at call time

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, LONG_PATH_REGISTRY_KEY) as key:
            value, _ = winreg.QueryValueEx(key, LONG_PATH_REGISTRY_VALUE)
        return bool(value)
    except (OSError, ValueError):
        return None


def enable_long_paths() -> tuple[bool, str]:
    """Set ``LongPathsEnabled`` to 1. Requires administrator rights.

    Returns:
        ``(succeeded, message)``. A permission error is reported, never
        swallowed: a station owner who is told this succeeded and reboots into
        an unchanged machine is worse off than one who is told to re-run
        elevated.
    """
    if sys.platform != "win32":
        return False, "not Windows; nothing to enable"
    try:
        import winreg  # noqa: PLC0415 -- Windows-only, imported at call time

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            LONG_PATH_REGISTRY_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, LONG_PATH_REGISTRY_VALUE, 0, winreg.REG_DWORD, 1)
    except PermissionError:
        return False, "permission denied -- re-run from an elevated prompt"
    except OSError as exc:
        return False, f"could not write the registry value: {exc}"
    return True, "LongPathsEnabled set to 1 -- reboot, then re-run to confirm"


def probe_root(root: str, target: int = 300) -> ProbeResult:
    """Empirically measure the longest usable path under ``root``.

    Creates ``<root>/STATES/.helao_longpath_probe`` and then one nested
    directory at a time until the full file path would exceed ``target``,
    exercising at each depth the operations the run tree actually needs:
    ``makedirs``, write, ``os.replace`` onto the target, read back, and
    ``listdir``. Everything created is removed again, deepest first.

    Creating the levels individually rather than in one ``makedirs`` call is
    what makes a failure informative: the reported ``reached`` is the measured
    ceiling, which distinguishes "long paths are off" (stops near 260) from "the
    root is not writable at all" (stops at 0).

    Args:
        root: Station data root, e.g. ``C:\\INST_hlo\\DATA``. The probe runs
            under its ``STATES`` subdirectory.
        target: Path length to exceed before declaring success.

    Returns:
        A :class:`ProbeResult`. Never raises for an ordinary filesystem
        failure; the failure is recorded in ``error`` instead.
    """
    result = ProbeResult(target=target)
    base = os.path.join(os.path.abspath(root), "STATES", _PROBE_DIRNAME)
    created: list[str] = []

    try:
        os.makedirs(base, exist_ok=True)
        created.append(base)
    except OSError as exc:
        result.error = f"could not create the probe directory {base}: {exc}"
        return result

    current = base
    try:
        while True:
            leaf = os.path.join(current, "probe.txt")
            if len(leaf) > target:
                # Deep enough to prove the point; verify at this depth and stop.
                if _exercise(leaf):
                    result.reached = max(result.reached, len(leaf))
                else:
                    result.error = f"file operations failed at {len(leaf)} characters"
                break
            if _exercise(leaf):
                result.reached = max(result.reached, len(leaf))
            else:
                result.error = (
                    f"file operations failed at {len(leaf)} characters, "
                    f"below the {target}-character target"
                )
                break
            nxt = os.path.join(current, _COMPONENT)
            try:
                os.mkdir(nxt)
            except FileExistsError:
                pass
            except OSError as exc:
                result.error = (
                    f"could not create a directory at {len(nxt)} characters: {exc}"
                )
                break
            created.append(nxt)
            current = nxt
    finally:
        for path in reversed(created):
            leaf = os.path.join(path, "probe.txt")
            for victim, remove in ((leaf, os.remove), (path, os.rmdir)):
                try:
                    remove(victim)
                except FileNotFoundError:
                    pass
                except OSError:
                    result.cleaned = False
                    result.leftover.append(victim)

    result.ok = result.reached > target and result.error is None
    return result


def _exercise(leaf: str) -> bool:
    """Write, atomically replace, read back and list ``leaf``; report success.

    Mirrors what a meta writer actually does, so a platform that allows
    ``open`` but not ``os.replace`` at this length is caught here rather than
    at a station three weeks later.
    """
    staging = os.path.join(os.path.dirname(leaf), ".probe.tmp")
    try:
        with open(staging, "w", encoding="utf-8") as handle:
            handle.write("helao long path probe\n")
        os.replace(staging, leaf)
        with open(leaf, encoding="utf-8") as handle:
            if handle.read() != "helao long path probe\n":
                return False
        return os.path.basename(leaf) in os.listdir(os.path.dirname(leaf))
    except OSError:
        try:
            os.remove(staging)
        except OSError:
            pass
        return False


def main(argv: Optional[list[str]] = None) -> int:
    """Report the long-path status of a root, optionally enabling it first.

    Args:
        argv: Argument list excluding the program name; defaults to
            ``sys.argv[1:]``.

    Returns:
        Process exit status: 0 only when the probe cleared ``--target``.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    target = 300
    if "--target" in argv:
        idx = argv.index("--target")
        try:
            target = int(argv[idx + 1])
        except (IndexError, ValueError):
            print("--target needs an integer, e.g. --target 300")
            return 1
        del argv[idx : idx + 2]
    do_enable = "--enable" in argv
    roots = [a for a in argv if not a.startswith("--")]
    if len(roots) != 1:
        print(__doc__)
        return 1
    root = roots[0]

    print(f"platform:          {sys.platform}")
    if sys.platform != "win32":
        print("There is no 260-character ceiling on this platform.")

    if do_enable:
        ok, message = enable_long_paths()
        print(f"--enable:          {'ok' if ok else 'FAILED'} -- {message}")
        if not ok:
            return 1

    reg = registry_long_paths_enabled()
    reg_text = {True: "1 (enabled)", False: "0 (disabled)", None: "unreadable"}[reg]
    print(f"LongPathsEnabled:  {reg_text}")

    result = probe_root(root, target=target)
    print(f"probe root:        {root}")
    print(f"longest path used: {result.reached} characters (target > {target})")
    if result.error:
        print(f"probe error:       {result.error}")
    if not result.cleaned:
        print("probe cleanup:     INCOMPLETE, remove by hand:")
        for path in result.leftover:
            print(f"  {path}")

    if result.ok:
        print("RESULT: PASS -- no 260-character ceiling on this root.")
        return 0

    print("RESULT: FAIL -- the 260-character ceiling is still in place.")
    if sys.platform == "win32":
        if reg is not True:
            print(
                "  Fix: from an elevated prompt, run\n"
                f"    python -m helao.core.tests.check_long_paths {root} --enable\n"
                "  then reboot and re-run this without --enable."
            )
        else:
            print(
                "  LongPathsEnabled is already 1, so the interpreter is the other\n"
                "  half: a python.exe without a longPathAware manifest, or the\n"
                "  machine has not been rebooted since the value was set."
            )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
