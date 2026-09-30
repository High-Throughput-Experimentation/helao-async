"""Copy one finished sequence out of a station run root into a parity golden set.

Standalone and stdlib-only on purpose: it only copies files, so an operator can
copy this file anywhere and run it while a checkout that lacks the rest of this
branch (e.g. freeze/pre-legacy-removal_2608) is active. Run it by file path:

    python station_golden_capture.py --root C:\\INST_hlo\\DATA --seq <sequence dir name>
        --out <set dir> --config-prefix eche10_hex [--launch-cmd "<cmd>"]

Reads <root>, writes only <out> (which must not exist). Handles the unified
layout (RUNS, DIAG) and the legacy one (RUNS_FINISHED/SYNCED/NOSYNC/DIAG plus
PROCESSES). Exit 2 with a message on: sequence still under RUNS_ACTIVE, not
found, found in both layouts, or <out> already present.
"""

import argparse
import datetime
import glob
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

UNIFIED = ("RUNS", "DIAG")
LEGACY = ("RUNS_FINISHED", "RUNS_SYNCED", "RUNS_NOSYNC", "RUNS_DIAG")


def die(msg):
    print(f"station_golden_capture: {msg}", file=sys.stderr)
    sys.exit(2)


def find(root, tops, names):
    return [p for t in tops for n in names for p in sorted(root.glob(f"{t}/*/*/{n}"))]


def seq_text(match):
    """Text of the sequence's *-seq.yml, from the directory or from the zip."""
    if match.is_dir():
        ymls = sorted(match.glob("*-seq.yml"))
        return ymls[0].read_text(errors="replace") if ymls else ""
    with zipfile.ZipFile(match) as z:
        ymls = sorted(
            (n for n in z.namelist() if n.endswith("-seq.yml")),
            key=lambda n: n.count("/"),
        )
        return z.read(ymls[0]).decode(errors="replace") if ymls else ""


def scalar(text, key):
    # splitlines, not re.M: `$` only knows "\n", so a "\r"-, "\x85"- or
    # " "-separated yml hid a key that was plainly there (eche10, 2026-09-30)
    for line in text.lstrip("﻿").splitlines():
        if line.startswith(f"{key}:"):
            return line[len(key) + 1 :].strip().strip("'\"") or None
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--seq", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--config-prefix", required=True)
    ap.add_argument("--launch-cmd")
    a = ap.parse_args()

    seq = re.split(r"[\\/]", a.seq.rstrip("\\/"))[-1]  # a full path works too
    seq = seq[:-4] if seq.endswith(".zip") else seq
    names = tuple(glob.escape(n) for n in (seq, seq + ".zip"))
    if a.out.exists():
        die(f"--out {a.out} already exists; refusing to overwrite")
    if a.out.resolve().is_relative_to(a.root.resolve()):
        die(f"--out {a.out} is inside --root {a.root}; write outside the run root")
    active = [p for n in names for p in (a.root / "RUNS_ACTIVE").rglob(n)]
    if active:
        die(f"{seq} is under RUNS_ACTIVE ({active[0]}); let it drain first")
    unified = find(a.root, UNIFIED, names)
    legacy = find(a.root, LEGACY, names)
    if unified and legacy:
        die(f"{seq} found in both layouts: {unified[0]} and {legacy[0]}")
    matches = unified or legacy
    if not matches:
        die(f"{seq} not found under {a.root}")

    text = seq_text(sorted(matches, key=lambda p: p.suffix == ".zip")[0])
    for m in matches:
        dst = a.out / "root" / m.relative_to(a.root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if m.is_dir():
            shutil.copytree(m, dst)
        else:
            shutil.copy2(m, dst)

    n_prc = 0
    if legacy:
        uuid = scalar(text, "sequence_uuid")
        if not uuid:
            die(f"no sequence_uuid in the sequence's *-seq.yml under {legacy[0]}")
        proc = a.root / "PROCESSES"
        # the process's own top-level line, not a mention in its params
        for p in sorted(proc.rglob("*-prc.yml")) if proc.is_dir() else []:
            if scalar(p.read_text(errors="replace"), "sequence_uuid") == uuid:
                dst = a.out / "root" / "PROCESSES" / p.relative_to(proc)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst)
                n_prc += 1

    prefix = a.config_prefix
    ext = "py" if prefix.endswith("_hex") else "yml"
    fields = {
        "scenario": f"{prefix}-smoke",
        "config_prefix": prefix,
        "config_path": f"helao/deploy/hte/configs/{prefix}.{ext}",
        "legacy_git_sha": scalar(text, "hlo_version") or "unknown",
        "launch_cmd": a.launch_cmd or f"python launch.py {prefix} --no-hot-reload",
        "sequence_name": scalar(text, "sequence_name") or "unknown",
        "capture_timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "harness_version": "station_golden_capture",
    }
    # json.dumps gives a double-quoted scalar, valid YAML: "1e10" stays a string
    lines = [f"{k}: {json.dumps(v)}" for k, v in fields.items()]
    lines.insert(6, "sequence_params: {}")
    (a.out / "provenance.yml").write_text("\n".join(lines) + "\n")

    rels = ",".join(m.relative_to(a.root).as_posix() for m in matches)
    layout = "unified" if unified else "legacy"
    print(f"layout={layout} copied=[{rels}] prc={n_prc} out={a.out}")


if __name__ == "__main__":
    main()
