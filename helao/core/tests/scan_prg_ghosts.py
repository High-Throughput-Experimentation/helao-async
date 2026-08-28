"""Report ``.prg`` sidecars that recorded an atomic-write staging file.

The syncer learns an action's non-hlo files by globbing the record directory, so
anything transiently present there gets uploaded. Every meta and data writer in
this codebase stages ``.<name>.<uuid1hex>.tmp`` beside its target and renames it
into place, so a glob landing mid-write captures a name the rename has already
consumed. That race has two outcomes, and this reports both:

* the upload loses -- the name is recorded in ``files_pending`` and can never
  upload, which used to spin the push loop forever;
* the upload wins -- the staging bytes reach ``raw_data/`` as a permanent object
  and the name is recorded in ``files_s3``.

``HelaoYml._is_syncable_misc_file`` now excludes both shapes, so a sidecar
written by a current build cannot record one. This exists to find the ones
written before that landed. ``helao/core/tests/test_scan_prg_ghosts.py`` pins
this module's notion of a staging name to that method's, so the two cannot
drift.

Reads loose ``.prg`` files and ``.prg`` members inside sequence zips. Read-only:
nothing is written, moved, uploaded, or deleted. A recorded ghost is not
self-healing on the S3 side -- an entry still in ``files_pending`` is dropped by
``Progress.prune_missing_pending`` the next time the record is opened, but an
object already under ``raw_data/`` has to be removed by hand.

**Run this on the host that owns the data, never across a network mount.** The
first sweep of a production archive was run over an sshfs mount and reported a
clean "0 loose .prg" -- ``os.walk`` swallows ``OSError`` by default, transient
``Operation not permitted`` errors from fuse pruned whole subtrees, and the
result was a confident verdict at roughly 2% coverage. The same directories
listed fine on retry. Hence two deliberate choices here: every directory listing
is retried before it is given up on, and a listing that still fails is counted
and reported rather than skipped. Coverage is always printed, and incomplete
coverage is a non-zero exit, so a partial sweep can never be mistaken for a
clean one. Cross-check the record count against a plain ``find`` on the same
host before trusting a clean result.

Usage::

    python -m helao.core.tests.scan_prg_ghosts <DATA dir> [more dirs...]
    python -m helao.core.tests.scan_prg_ghosts /mnt/wd4/DATA

Given a run-tree root the ``RUNS_*`` subtrees are scanned; given anything else
the directory itself is walked, so a single week or sequence can be checked.

Exit status is 0 only when every record was read and none carried a staging
name; it is 1 when a ghost is found or when any directory could not be read, so
it can gate a cleanup sweep.
"""

__all__ = ["is_staging_name", "scan_root", "scan_prg_text", "Findings"]

import argparse
import os
import posixpath
import re
import sys
import time
import zipfile
from dataclasses import dataclass, field

# Parsing goes through the project's ``yml_load`` when the full environment is
# importable, so a sidecar is read exactly as the syncer reads it. Falling back
# to PyYAML's safe loader is what makes the instruction above -- run this on the
# host that owns the data -- actually possible: that host may have only a
# checkout and a stock python, while ``helao.helpers`` pulls in aiofiles and the
# rest of the runtime stack, none of which a read-only scan needs. With the
# fallback this file also runs directly (``python3 scan_prg_ghosts.py <dir>``),
# no PYTHONPATH required. A .prg is a plain mapping of scalars, lists and dicts,
# which both loaders read alike; a test pins that.
try:
    from helao.helpers.yml_tools import yml_load

    def _parse_yaml(text: str):
        return yml_load(text, fast=True)

except ImportError:  # pragma: no cover - the path taken on a bare data host
    import yaml

    def _parse_yaml(text: str):
        return yaml.safe_load(text)


# Retries per failed directory listing or file read. A network mount fails
# intermittently, and a single attempt turns that into silently missing records.
RETRIES = 4
RETRY_BACKOFF_S = 0.2

# Subtrees walked when the given directory looks like a run-tree root.
RUN_TREES = (
    "RUNS_ACTIVE",
    "RUNS_FINISHED",
    "RUNS_SYNCED",
    "RUNS_NOSYNC",
    "RUNS_DIAG",
    "RUNS_CORRUPT",
    "RUNS_REBUILD",
    "RUNS_SUPERSEDED",
)


def is_staging_name(recorded: str) -> bool:
    """Whether *recorded* names an atomic-write staging file rather than data.

    Mirrors the two independent exclusions in
    ``HelaoYml._is_syncable_misc_file``: the ``.tmp`` suffix catches a staging
    file written without the dotfile convention, and the leading dot catches the
    staging names of any future writer. Kept independent for the same reason
    they are there -- either alone would miss one shape.

    Recorded paths may be relative or absolute and may carry Windows
    separators, so the basename is taken after normalizing.
    """
    normalized = str(recorded).replace("\\", "/")
    basename = posixpath.basename(normalized)
    return normalized.endswith(".tmp") or basename.startswith(".")


@dataclass
class Findings:
    """What a scan saw. Counts are coverage; lists are what to act on."""

    n_prg: int = 0
    n_zip: int = 0
    uploaded: list = field(default_factory=list)  # (label, name, s3 key)
    pending: list = field(default_factory=list)  # (label, name)
    unreadable: list = field(default_factory=list)  # (path, reason)
    unparseable: list = field(default_factory=list)  # (label, reason)
    bad_zips: list = field(default_factory=list)  # path

    @property
    def n_ghosts(self) -> int:
        return len(self.uploaded) + len(self.pending)

    @property
    def complete(self) -> bool:
        """Whether every record was actually read."""
        return not self.unreadable


# A dot-led token in any of the three positions a recorded name can occupy: a
# mapping KEY (``  .name: key``), a sequence ITEM (``  - .name``), or a VALUE
# (``key: .name``). The first is the one that matters and the one a naive
# ``": ."``/``"- ."`` scan misses -- ``files_s3`` records names as keys, so a
# dotfile that does not also end in ``.tmp`` would slip through and the archive
# would be reported clean without ever being parsed.
_DOT_LED = re.compile(r"(?m)^\s*(?:-\s+)?\.\S|:\s+\.\S")


def _might_hold_ghost(text: str) -> bool:
    """Cheap reject before parsing YAML.

    Parsing every sidecar in a large archive is the dominant cost, so this skips
    the parse for documents that cannot match. Deliberately biased: a false
    positive costs one wasted parse, while a false negative reports a record as
    clean without ever looking inside it. A YAML float or a ``./`` path may
    therefore match, and that is fine.
    """
    return ".tmp" in text or _DOT_LED.search(text) is not None


def scan_prg_text(text: str, label: str, found: Findings) -> None:
    """Record any staging names in one ``.prg`` document."""
    if not _might_hold_ghost(text):
        return
    try:
        parsed = _parse_yaml(text)
    except Exception as exc:  # a damaged sidecar is a finding, not a crash
        found.unparseable.append((label, exc.__class__.__name__))
        return
    if not isinstance(parsed, dict):
        return
    uploaded = parsed.get("files_s3")
    if isinstance(uploaded, dict):
        for name, key in uploaded.items():
            if is_staging_name(name):
                found.uploaded.append((label, str(name), str(key)))
    pending = parsed.get("files_pending")
    if isinstance(pending, list):
        for name in pending:
            if is_staging_name(name):
                found.pending.append((label, str(name)))


def _read_text(path: str, found: Findings) -> str:
    """Read *path*, retrying, and record it as unreadable if it never opens."""
    for attempt in range(RETRIES):
        try:
            with open(path, "r", errors="replace") as handle:
                return handle.read()
        except OSError as exc:
            last = exc
            time.sleep(RETRY_BACKOFF_S * (attempt + 1))
    found.unreadable.append((path, f"{last.__class__.__name__}: {last}"))
    return ""


def _scan_zip(path: str, found: Findings) -> None:
    """Scan the ``.prg`` members of one sequence zip."""
    for attempt in range(RETRIES):
        try:
            with zipfile.ZipFile(path) as archive:
                for member in archive.namelist():
                    if not member.endswith(".prg"):
                        continue
                    try:
                        raw = archive.read(member)
                    except Exception as exc:
                        found.unparseable.append(
                            (f"{path}::{member}", exc.__class__.__name__)
                        )
                        continue
                    text = raw.decode("utf-8", errors="replace")
                    scan_prg_text(text, f"{path}::{member}", found)
            return
        except zipfile.BadZipFile:
            # Damaged archives are a known, separate campaign; report and move on.
            found.bad_zips.append(path)
            return
        except OSError as exc:
            last = exc
            time.sleep(RETRY_BACKOFF_S * (attempt + 1))
    found.unreadable.append((path, f"{last.__class__.__name__}: {last}"))


def _listdir(path: str):
    """``scandir`` with retries. Returns ``(entries, error)``."""
    last = None
    for attempt in range(RETRIES):
        try:
            return list(os.scandir(path)), None
        except OSError as exc:
            last = exc
            time.sleep(RETRY_BACKOFF_S * (attempt + 1))
    return [], last


def scan_root(root: str, found: Findings, progress_every: int = 0) -> None:
    """Walk *root* iteratively, scanning every ``.prg`` and sequence zip.

    An explicit stack rather than recursion: run trees nest a directory per
    week, day, sequence, experiment and action, and a recursive walk of a deep
    archive is one more thing that can fail for a reason unrelated to the data.
    """
    stack = [root]
    while stack:
        current = stack.pop()
        entries, error = _listdir(current)
        if error is not None:
            found.unreadable.append((current, f"{error.__class__.__name__}: {error}"))
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError as exc:
                found.unreadable.append((entry.path, exc.__class__.__name__))
                continue
            if entry.name.endswith(".prg"):
                found.n_prg += 1
                text = _read_text(entry.path, found)
                if text:
                    scan_prg_text(text, entry.path, found)
            elif entry.name.endswith(".zip"):
                found.n_zip += 1
                _scan_zip(entry.path, found)
            else:
                continue
            total = found.n_prg + found.n_zip
            if progress_every and total % progress_every == 0:
                print(
                    f"  ... {total} records ({found.n_prg} prg, {found.n_zip} zip), "
                    f"{found.n_ghosts} ghosts",
                    file=sys.stderr,
                    flush=True,
                )


def _roots_under(path: str) -> list:
    """The run trees under *path*, or *path* itself when it holds none."""
    trees = [
        os.path.join(path, name)
        for name in RUN_TREES
        if os.path.isdir(os.path.join(path, name))
    ]
    return trees or [path]


def main(argv=None) -> int:
    """Scan each directory given on the command line."""
    parser = argparse.ArgumentParser(
        description=(
            "Report .prg sidecars that recorded an atomic-write staging file. "
            "Read-only. Run on the host that owns the data, not over a mount."
        )
    )
    parser.add_argument(
        "data_dirs",
        nargs="+",
        metavar="DATA_DIR",
        help="a run-tree root (its RUNS_* subtrees are scanned), or any directory",
    )
    parser.add_argument(
        "--progress",
        type=int,
        default=0,
        metavar="N",
        help="print coverage to stderr every N records (0 = silent)",
    )
    args = parser.parse_args(argv)

    found = Findings()
    for data_dir in args.data_dirs:
        for root in _roots_under(data_dir):
            print(f"scanning {root}")
            scan_root(root, found, args.progress)

    print(
        f"\ncoverage: {found.n_prg} loose .prg, {found.n_zip} zips, "
        f"{len(found.unreadable)} unreadable, {len(found.bad_zips)} damaged zips"
    )

    for label, name, key in found.uploaded:
        print(f"  UPLOADED   {name}\n             s3: {key}\n             in: {label}")
    for label, name in found.pending:
        print(f"  PENDING    {name}\n             in: {label}")
    for label, reason in found.unparseable:
        print(f"  UNREADABLE {label}: {reason}")
    for path in found.bad_zips:
        print(f"  DAMAGED    {path}")
    for path, reason in found.unreadable:
        print(f"  MISSED     {path}: {reason}")

    if found.pending:
        print(
            f"\n{len(found.pending)} pending entr(ies) will be dropped by "
            "Progress.prune_missing_pending the next time each record is opened."
        )
    if found.uploaded:
        print(
            f"\n{len(found.uploaded)} staging file(s) reached the bucket and must "
            "be removed by hand. Confirm each one's finished counterpart is "
            "present before deleting it."
        )
    if not found.complete:
        print(
            f"\nCoverage is INCOMPLETE: {len(found.unreadable)} path(s) could not "
            "be read after retries, so a clean result here would be meaningless."
        )
    elif not found.n_ghosts:
        print("\nNo staging files recorded in any sidecar.")

    return 1 if found.n_ghosts or not found.complete else 0


if __name__ == "__main__":
    sys.exit(main())
