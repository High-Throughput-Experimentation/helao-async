"""Report which ``STATES/queues*.pck`` files this build could actually restore.

An orchestrator pickle can become unrestorable in two independent ways, and this
reports both without ever loading (and therefore never executing) a pickle:

* it references a class that no longer exists -- unpickling would raise, and
  :meth:`QueuePersister.import_queues` quarantines the file as
  ``queues_unreadable_<ts>.pck``;
* its payload layout predates or postdates :data:`QUEUE_PCK_SCHEMA` -- the import
  declines it and starts with empty queues.

Class references are read straight from the pickle opcode stream via
``pickletools.genops``, which walks the bytes without building any objects, so
scanning a hostile or corrupt file is safe. Each referenced ``helao.*`` class is
then resolved against the current tree to see whether it still exists.

Read-only: nothing is written, moved, or deleted. Use it to find the files worth
removing by hand, then remove them yourself.

Usage::

    python -m helao.core.tests.check_queue_pcks <STATES dir> [more dirs...]
    python -m helao.core.tests.check_queue_pcks C:\\INST_hlo\\STATES

Exit status is 0 when every file is restorable, 1 when any is not, so it can gate
a sweep script.
"""

__all__ = ["scan_dir", "scan_file", "referenced_classes"]

import argparse
import glob
import importlib
import os
import pickletools
import sys

from helao.core.servers.orch_persist import (
    QUEUE_PCK_SCHEMA,
    TIMESTAMPED_EXPORT_RETENTION,
    _TIMESTAMPED_EXPORT_RE,
)

# Opcodes carrying a class reference. STACK_GLOBAL takes the module and name from
# the two preceding string operands; the older GLOBAL packs both into one operand.
_STACK_GLOBAL = "STACK_GLOBAL"
_GLOBAL = "GLOBAL"
_STRING_OPCODES = (
    "SHORT_BINUNICODE",
    "BINUNICODE",
    "BINUNICODE8",
    "UNICODE",
    "SHORT_BINSTRING",
    "BINSTRING",
    "STRING",
)


def referenced_classes(path: str) -> tuple:
    """Return ``(refs, error)`` for the class references inside ``path``.

    Args:
        path: Pickle file to inspect.

    Returns:
        ``(refs, error)`` where ``refs`` is a set of ``(module, name)`` pairs the
        unpickler would resolve, and ``error`` is ``None`` or a short description
        if the opcode stream could not be walked.
    """
    refs = set()
    recent = []
    try:
        with open(path, "rb") as f:
            for opcode, arg, _pos in pickletools.genops(f):
                if opcode.name in _STRING_OPCODES:
                    recent.append(arg)
                    del recent[:-2]
                elif opcode.name == _STACK_GLOBAL:
                    if len(recent) == 2:
                        refs.add((recent[0], recent[1]))
                    recent = []
                elif opcode.name == _GLOBAL:
                    parts = str(arg).split()
                    if len(parts) == 2:
                        refs.add((parts[0], parts[1]))
                    recent = []
    except Exception as exc:
        return refs, f"{type(exc).__name__}: {exc}"
    return refs, None


def _missing(refs) -> list:
    """Which ``helao.*`` references in ``refs`` no longer resolve."""
    gone = []
    for module, name in sorted(refs):
        if not module.startswith("helao"):
            # Stdlib/third-party references are not ours to police, and importing
            # arbitrary modules to check them would be a side effect.
            continue
        try:
            if not hasattr(importlib.import_module(module), name):
                gone.append(f"{module}.{name}")
        except Exception:
            gone.append(f"{module} (not importable)")
    return gone


def _schema_of(path: str):
    """Best-effort payload schema value, read from the opcode stream.

    Looks for the string ``"schema"`` followed by an integer operand, which is how
    :meth:`QueuePersister.export_queues` writes it. Returns ``None`` when absent,
    which is also what a pre-stamp pickle looks like.
    """
    try:
        with open(path, "rb") as f:
            seen_key = False
            for opcode, arg, _pos in pickletools.genops(f):
                if opcode.name in _STRING_OPCODES and arg == "schema":
                    seen_key = True
                elif seen_key and opcode.name.startswith(("BININT", "INT", "LONG")):
                    return arg
                elif seen_key and opcode.name in _STRING_OPCODES:
                    seen_key = False
    except Exception:
        return None
    return None


def scan_file(path: str) -> tuple:
    """Classify one pickle.

    Returns:
        ``(verdict, detail)`` where verdict is ``"ok"``, ``"stale"`` or
        ``"unparseable"``.
    """
    refs, error = referenced_classes(path)
    if error:
        return "unparseable", error
    gone = _missing(refs)
    if gone:
        return "stale", f"references missing {', '.join(gone)}"
    schema = _schema_of(path)
    if schema != QUEUE_PCK_SCHEMA:
        return (
            "stale",
            f"payload schema {schema!r}, this build restores only "
            f"{QUEUE_PCK_SCHEMA!r}",
        )
    return "ok", f"schema {schema!r}, {len(refs)} class reference(s)"


def scan_dir(states_dir: str) -> int:
    """Print a verdict per ``queues*.pck`` in ``states_dir``.

    Returns:
        Count of files this build could not restore.
    """
    paths = sorted(glob.glob(os.path.join(states_dir, "queues*.pck")))
    print(f"{states_dir}: {len(paths)} queue pickle(s)")
    if not paths:
        return 0
    bad = 0
    for path in paths:
        verdict, detail = scan_file(path)
        if verdict != "ok":
            bad += 1
        label = {"ok": "ok        ", "stale": "STALE     ", "unparseable": "UNREADABLE"}
        print(f"  {label[verdict]} {os.path.basename(path)}: {detail}")
    series = [p for p in paths if _TIMESTAMPED_EXPORT_RE.match(os.path.basename(p))]
    if len(series) > TIMESTAMPED_EXPORT_RETENTION:
        print(
            f"  note: {len(series)} timestamped exports present, above the "
            f"retention of {TIMESTAMPED_EXPORT_RETENTION}. export_queues() prunes "
            f"these on its next timestamped write; an idle orchestrator will not "
            f"trigger that."
        )
    return bad


def main(argv=None) -> int:
    """Scan each directory given on the command line."""
    parser = argparse.ArgumentParser(
        description=(
            "Report which STATES/queues*.pck files this build could restore. "
            "Read-only; never loads a pickle."
        )
    )
    parser.add_argument(
        "states_dirs",
        nargs="+",
        metavar="STATES_DIR",
        help="a STATES directory holding queues*.pck files",
    )
    args = parser.parse_args(argv)
    bad = sum(scan_dir(d) for d in args.states_dirs)
    print(
        f"\n{bad} file(s) this build cannot restore."
        if bad
        else "\nAll queue pickles are restorable by this build."
    )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
