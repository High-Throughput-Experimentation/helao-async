"""Regenerate the pinned conda env files from fresh solves of the dev env files.

For each platform, ``<prefix>_dev_<platform>.yml`` is solved from scratch
(dry run, nothing installed) and ``<prefix>_pinned_<platform>.yml`` plus
``requirements_pinned_<platform>.txt`` (the pip pins, installed with uv after
conda) are rewritten against that solve:

* a pinned conda package takes the solved version, written as ``name=version``
  with no build string;
* a pinned conda package the fresh solve no longer installs is dropped;
* a pinned pip package takes the version pip resolves for the target platform
  from ``requirements.txt`` (the dev pip list); one pip cannot resolve is
  kept as-is;
* pip lines that install from a URL are kept verbatim and never pinned;
* packages the solve adds that are not already pinned are reported, not added.

Before anything is written, the rewritten conda pins are solved again on
their platform, so a file that would not install is never written. Windows
files are solved from Linux with ``--platform win-64``; that covers which
versions exist and fit together, not a real install.

    python repin_envs.py                 # report only, parent env files
    python repin_envs.py --write         # rewrite the pinned files
    python repin_envs.py --root <dir> --prefix <name>   # another repo's files
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PIP_PLATFORMS = {
    "linux-64": [
        "manylinux2014_x86_64",
        "manylinux_2_17_x86_64",
        "manylinux_2_28_x86_64",
        "manylinux_2_34_x86_64",
        "linux_x86_64",
    ],
    "win-64": ["win_amd64"],
}
CONDA_PIN = re.compile(r"^  - ([A-Za-z0-9_.\-]+)=([^=\s]+)(?:=\S+)?$")
PIP_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)==(\S+)$")


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_dev(path: Path, requirements: Path) -> tuple[list[str], list[str], list[str]]:
    """Return (channels, conda specs, pip specs without URLs).

    Channels and conda specs come from the dev env file, pip specs from the
    requirements file; blank lines, comments and URL lines are skipped.
    """
    channels, conda, section = [], [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("channels:"):
            section = "channels"
        elif line.startswith("dependencies:"):
            section = "deps"
        elif line.startswith("  - "):
            (channels if section == "channels" else conda).append(line[4:].strip())
    pip = [
        s
        for s in requirements.read_text(encoding="utf-8").splitlines()
        if s.strip() and not s.lstrip().startswith("#") and "://" not in s
    ]
    return channels, conda, [s.strip() for s in pip]


def conda_solve(
    channels: list[str], specs: list[str], platform: str, solver: str
) -> dict[str, str]:
    """Dry-run solve `specs` for `platform`; return {name: version}."""
    conda = os.environ.get("CONDA_EXE") or shutil.which("conda") or "conda"
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [conda, "create", "--dry-run", "--json", f"--solver={solver}"]
        cmd += ["--platform", platform, "-p", str(Path(tmp) / "env")]
        cmd += ["--override-channels"] + [a for c in channels for a in ("-c", c)]
        out = subprocess.run(cmd + specs, capture_output=True, text=True).stdout
    try:
        result = json.loads(out)
    except json.JSONDecodeError:
        raise SystemExit(f"conda solve for {platform} printed no JSON:\n{out[-2000:]}")
    if not result.get("success"):
        msg = result.get("message") or result.get("error") or out[-2000:]
        raise SystemExit(f"conda solve for {platform} failed:\n{msg}")
    return {p["name"]: p["version"] for p in result["actions"]["LINK"]}


def pip_resolve(specs: list[str], platform: str, python: str) -> dict[str, str]:
    """Resolve pip `specs` for the target platform; return {normalized name: version}."""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        cmd = [sys.executable, "-m", "pip", "install", "--dry-run", "--quiet"]
        cmd += ["--ignore-installed", "--report", str(report)]
        cmd += ["--target", str(Path(tmp) / "t"), "--only-binary=:all:"]
        cmd += ["--python-version", python, "--implementation", "cp"]
        cmd += [a for p in PIP_PLATFORMS[platform] for a in ("--platform", p)]
        run = subprocess.run(cmd + specs, capture_output=True, text=True)
        if run.returncode:
            raise SystemExit(
                f"pip resolve for {platform} failed:\n{run.stderr[-2000:]}"
            )
        items = json.loads(report.read_text(encoding="utf-8"))["install"]
    return {norm(i["metadata"]["name"]): i["metadata"]["version"] for i in items}


def regenerate_pip(text: str, pip: dict[str, str]) -> tuple[str, list[str]]:
    """Rewrite a pinned requirements file's text against resolved versions.

    Returns the new text and human-readable report lines. Line endings are
    preserved, so a CRLF file stays CRLF.
    """
    eol = "\r\n" if "\r\n" in text else "\n"
    out, report = [], []
    for line in text.splitlines():
        if m := PIP_PIN.match(line):
            new = pip.get(norm(m[1]))
            if new is None:
                report.append(f"  pip {m[1]}=={m[2]}: not resolved, kept")
            else:
                if new != m[2]:
                    report.append(f"  pip {m[1]}: {m[2]} -> {new}")
                line = f"{m[1]}=={new}"
        out.append(line)
    return eol.join(out) + eol, report


def regenerate(text: str, conda: dict[str, str]) -> tuple[str, list[str]]:
    """Rewrite a pinned env file's text against solved conda versions.

    Returns the new text and human-readable report lines. Line endings are
    preserved, so a CRLF file stays CRLF.
    """
    eol = "\r\n" if "\r\n" in text else "\n"
    out, report = [], []
    for line in text.splitlines():
        if m := CONDA_PIN.match(line):
            new = conda.get(m[1])
            if new is None:
                report.append(f"  drop {m[1]}={m[2]}: not in the fresh solve")
                continue
            if new != m[2]:
                report.append(f"  {m[1]}: {m[2]} -> {new}")
            line = f"  - {m[1]}={new}"
        out.append(line)
    return eol.join(out) + eol, report


def conda_pins(text: str) -> list[str]:
    pins = []
    for line in text.splitlines():
        if m := CONDA_PIN.match(line):
            pins.append(f"{m[1]}=={m[2]}")
    return pins


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Regenerate the pinned conda env files.")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument("--prefix", default="helao")
    ap.add_argument("--platforms", nargs="+", default=["linux-64", "win-64"])
    ap.add_argument("--solver", default="rattler")
    ap.add_argument("--write", action="store_true", help="rewrite the pinned files")
    args = ap.parse_args(argv)

    for platform in args.platforms:
        dev = args.root / f"{args.prefix}_dev_{platform}.yml"
        pinned = args.root / f"{args.prefix}_pinned_{platform}.yml"
        pinned_pip = args.root / f"requirements_pinned_{platform}.txt"
        channels, conda_specs, pip_specs = read_dev(dev, args.root / "requirements.txt")
        print(f"== {pinned.name}: solving {dev.name} for {platform}")
        conda = conda_solve(channels, conda_specs, platform, args.solver)
        python = ".".join(conda["python"].split(".")[:2])
        pip = pip_resolve(pip_specs, platform, python) if pip_specs else {}

        old = pinned.read_bytes().decode()
        new, report = regenerate(old, conda)
        old_pip = pinned_pip.read_bytes().decode()
        new_pip, pip_report = regenerate_pip(old_pip, pip)
        report += pip_report
        pinned_names = {p.split("==")[0] for p in conda_pins(new)}
        added = sorted(set(conda) - pinned_names)
        print("\n".join(report) or "  no version changes")
        if added:
            print(f"  not pinned (solve installs them, not added): {', '.join(added)}")

        conda_solve(channels, conda_pins(new), platform, args.solver)
        print(f"  rewritten pins solve on {platform}")
        if args.write and new != old:
            pinned.write_bytes(new.encode())
            print(f"  wrote {pinned}")
        if args.write and new_pip != old_pip:
            pinned_pip.write_bytes(new_pip.encode())
            print(f"  wrote {pinned_pip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
