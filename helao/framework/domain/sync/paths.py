"""Pure path & status math for the HELAO data syncer.

Ported from the legacy ``helao/core/drivers/data/sync_driver.py``
(``HelaoYml`` properties, the ``move_to_synced``/``revert_to_finished`` module
functions, and ``HelaoSyncer._rel_under_runs``/``_node_keys``). Everything here
is **pure**: only ``pathlib.PurePosixPath`` math and ``datetime`` parsing, no
disk access. Filenames and ``RUNS_*`` segments are kept byte-identical to the
legacy layout so historical data and the live syncer stay compatible.

The on-disk layout is::

    <runs>/<week>/<date>/<seq>/<exp>/<act>/<name>-{seq,exp,act}.yml
"""
from __future__ import annotations

from datetime import datetime
from pathlib import PurePath, PurePosixPath
from typing import Sequence

# RUNS_* tree segment names, in lifecycle order. (legacy status_idx valid set)
RUNS: tuple[str, str, str] = ("RUNS_ACTIVE", "RUNS_FINISHED", "RUNS_SYNCED")

# Filename-suffix abbreviation -> record type. (legacy module constant)
ABR_MAP: dict[str, str] = {"act": "action", "exp": "experiment", "seq": "sequence"}


def _as_purepath(path: "str | PurePath") -> PurePosixPath:
    """Normalize any path-like input to a ``PurePosixPath`` (no disk access)."""
    if isinstance(path, PurePosixPath):
        return path
    if isinstance(path, PurePath):
        # Reinterpret an arbitrary PurePath's string form as posix.
        return PurePosixPath(str(path))
    return PurePosixPath(path)


def _stem(yml_name: "str | PurePath") -> str:
    """Return the filename stem (no suffix) for a name or full path."""
    return _as_purepath(yml_name).stem


def node_type(yml_name: "str | PurePath") -> str:
    """Return ``"act"``/``"exp"``/``"seq"`` from the yml filename suffix.

    Legacy: ``HelaoYml.type`` (``self.target.stem.split("-")[-1]``), but this
    returns the abbreviation rather than the expanded ``ABR_MAP`` value.
    """
    return _stem(yml_name).split("-")[-1]


def node_timestamp(yml_name: "str | PurePath") -> datetime:
    """Parse the record timestamp from the yml filename.

    Legacy: ``HelaoYml.timestamp`` — tries ``%y%m%d.%H%M%S%f`` then falls back
    to the 4-digit-year ``%Y%m%d.%H%M%S%f`` form.
    """
    head = _stem(yml_name).split("-")[0]
    try:
        return datetime.strptime(head, "%y%m%d.%H%M%S%f")
    except ValueError:
        return datetime.strptime(head, "%Y%m%d.%H%M%S%f")


def status_idx(parts: "str | PurePath | Sequence[str]") -> int:
    """Index of the ``RUNS_{ACTIVE,FINISHED,SYNCED}`` segment in ``parts``.

    Legacy: ``HelaoYml.status_idx``. Accepts a path-like or an already-split
    parts sequence.

    Raises:
        ValueError: if no valid ``RUNS_*`` segment is present.
    """
    seq = _parts(parts)
    for i, x in enumerate(seq):
        if x in RUNS:
            return i
    raise ValueError(f"{parts!r} is not located within a Helao RUNS_* directory")


def _parts(parts: "str | PurePath | Sequence[str]") -> tuple[str, ...]:
    """Coerce a path-like or parts-sequence to a tuple of segments."""
    if isinstance(parts, (str, PurePath)):
        return _as_purepath(parts).parts
    return tuple(parts)


def status_of(parts: "str | PurePath | Sequence[str]") -> str:
    """Return ``"active"``/``"finished"``/``"synced"`` from the ``RUNS_*`` segment.

    Legacy: ``HelaoYml.status`` (first ``RUNS_*`` part, split on ``_``, lower).
    """
    seq = _parts(parts)
    runs = [x for x in seq if x.startswith("RUNS_")]
    return runs[0].split("_")[-1].lower()


def rename_status(path: "str | PurePath", new_status: str) -> PurePosixPath:
    """Return ``path`` with its ``RUNS_*`` segment replaced by ``new_status``.

    Generalizes legacy ``HelaoYml.rename``; ``new_status`` is the lowercase
    status name (``"active"``/``"finished"``/``"synced"``), rewritten to the
    ``RUNS_<UPPER>`` segment.
    """
    p = _as_purepath(path)
    parts = list(p.parts)
    parts[status_idx(parts)] = f"RUNS_{new_status.upper()}"
    return PurePosixPath(*parts)


def active_path(path: "str | PurePath") -> PurePosixPath:
    """``path`` rewritten under ``RUNS_ACTIVE`` (legacy ``HelaoYml.active_path``)."""
    return rename_status(path, "active")


def finished_path(path: "str | PurePath") -> PurePosixPath:
    """``path`` rewritten under ``RUNS_FINISHED`` (legacy ``HelaoYml.finished_path``)."""
    return rename_status(path, "finished")


def synced_path(path: "str | PurePath") -> PurePosixPath:
    """``path`` rewritten under ``RUNS_SYNCED`` (legacy ``HelaoYml.synced_path``)."""
    return rename_status(path, "synced")


def relative_under_runs(path: "str | PurePath") -> "str | None":
    """Return ``path`` relative to its ``RUNS_*`` root as a ``/``-joined string.

    Legacy: ``HelaoSyncer._rel_under_runs`` / ``HelaoYml.relative_path``.
    Returns ``None`` when no ``RUNS_*`` segment is present.
    """
    parts = _as_purepath(path).parts
    run_idxs = [i for i, x in enumerate(parts) if x.startswith("RUNS_")]
    if not run_idxs:
        return None
    return "/".join(parts[run_idxs[0] + 1 :])


def compute_synced_path(path: "str | PurePath") -> PurePosixPath:
    """FINISHED->SYNCED path rewrite (legacy ``move_to_synced`` math).

    Mirrors legacy behavior: a plain ``RUNS_FINISHED`` -> ``RUNS_SYNCED`` string
    replacement; a no-op (returns the same path) when already under
    ``RUNS_SYNCED``.
    """
    return PurePosixPath(str(_as_purepath(path)).replace("RUNS_FINISHED", "RUNS_SYNCED"))


def compute_finished_path(path: "str | PurePath") -> PurePosixPath:
    """SYNCED->FINISHED path rewrite (legacy ``revert_to_finished`` math).

    Raises:
        ValueError: if ``RUNS_SYNCED`` is not present (matches legacy
        ``parts.index("RUNS_SYNCED")``).
    """
    p = _as_purepath(path)
    parts = list(p.parts)
    state_index = parts.index("RUNS_SYNCED")  # raises ValueError if absent
    parts[state_index] = "RUNS_FINISHED"
    return PurePosixPath(*parts)


def node_keys(yml_path: "str | PurePath") -> "tuple[str | None, str | None]":
    """Return ``(seq_key, exp_key)`` lock keys for ``yml_path``.

    Legacy: ``HelaoSyncer._node_keys``. Keys are the sequence/experiment
    *directory* paths relative to the ``RUNS_*`` root. ``exp_key`` is ``None``
    for sequences. ``(None, None)`` when not under ``RUNS_*`` or for an unknown
    suffix.
    """
    rel = relative_under_runs(yml_path)
    if rel is None:
        return None, None
    parts = rel.split("/")
    stem = _stem(yml_path)
    if stem.endswith("-seq"):
        return "/".join(parts[:-1]), None
    if stem.endswith("-exp"):
        return "/".join(parts[:-2]), "/".join(parts[:-1])
    if stem.endswith("-act"):
        return "/".join(parts[:-3]), "/".join(parts[:-2])
    return None, None


def prg_path(yml_path: "str | PurePath") -> PurePosixPath:
    """Return the ``.prg`` sidecar path: same dir+stem, ``.prg`` suffix.

    Legacy ``Progress`` builds the prg as ``yml.synced_path.with_suffix(".prg")``;
    this is the pure same-dir form (the caller chooses the tree).
    """
    return _as_purepath(yml_path).with_suffix(".prg")
