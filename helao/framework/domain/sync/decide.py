"""Pure decision core of the legacy ``sync_yml`` pipeline.

Ported from ``helao/core/drivers/data/sync_driver.py``:

* the ``sync_yml`` head decision state machine + re-queue rank logic
  (lines 1027-1106) -> :func:`decide_sync`;
* the pending-file-list build (lines 1108-1117) -> :func:`build_upload_file_list`;
* the hlo-vs-parquet upload decision / 1GB size threshold (lines 1123-1159)
  -> :func:`hlo_upload_plan`;
* the metadata patch -- ``MOD_PATCH`` key rename + technique-name list split
  (lines 1229-1237) -> :func:`patch_metadata`.

This module is part of the PURE ``domain/`` layer: stdlib only
(``dataclasses``/``enum``/``copy``), no disk I/O, no asyncio, no adapters. The
*imperative* pipeline (queue ops, S3 upload, tree moves, the pydantic-model
``clean_dict`` round-trip) lives in the ``app`` layer and consumes these
deciders.

Semantics are kept byte-identical to legacy. Re-queue ranks in particular are
copied verbatim: see :func:`decide_sync`.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Sequence

# Legacy ``MOD_PATCH`` (sync_driver.py line 75): yml metadata keys renamed
# before the model round-trip. Kept identical so shipped JSON matches legacy.
MOD_PATCH: dict[str, str] = {
    "exid": "exec_id",
}


class SyncAction(str, Enum):
    """Outcome of the :func:`decide_sync` head state machine.

    Mirrors the four legacy ``sync_yml`` exits (lines 1027-1106):

    * ``SKIP`` -- yml missing or already synced; legacy ``return True``.
    * ``SOFT_BLOCK`` -- yml still ``active``; legacy ``return False`` (no
      re-queue, just wait for it to finish).
    * ``REQUEUE_CHILDREN`` -- a non-action whose children are not all synced;
      legacy re-enqueues the children then itself and ``return False``.
    * ``PROCEED`` -- finished, children synced; ready to upload/move.
    """

    SKIP = "skip"
    SOFT_BLOCK = "soft_block"
    REQUEUE_CHILDREN = "requeue"
    PROCEED = "proceed"


@dataclass(frozen=True)
class RequeueItem:
    """A single (relpath, rank) re-enqueue request.

    ``relpath`` is the path of the node to re-queue relative to its ``RUNS_*``
    root (the empty string ``""`` denotes *self* -- the node being decided --
    so the caller maps it back to the original yml path). ``rank`` is the
    PriorityQueue priority to re-enqueue at (lower == higher priority).
    """

    relpath: str
    rank: int


@dataclass(frozen=True)
class SyncDecision:
    """Tagged result of :func:`decide_sync` (mirrors SP5 ``OrchDecision``).

    ``requeue`` is populated only for :attr:`SyncAction.REQUEUE_CHILDREN`; it
    lists the unsynced children (at the child rank) followed by self (at the
    parent rank), in legacy enqueue order.
    """

    action: SyncAction
    requeue: tuple[RequeueItem, ...] = ()


def decide_sync(
    *,
    exists: bool,
    node_status: str,
    child_statuses: Sequence[tuple[str, str]],
    already_synced: bool,
    rank: int,
) -> SyncDecision:
    """Decide what to do with one yml in the sync pipeline (PURE).

    Mirrors legacy ``sync_yml`` lines 1027-1106 exactly:

    1. ``not exists`` -> ``SKIP`` (legacy 1027-1031: yml moved to synced).
    2. ``already_synced`` or ``node_status == "synced"`` -> ``SKIP``
       (legacy 1044-1048: status already 'synced').
    3. ``node_status == "active"`` -> ``SOFT_BLOCK``
       (legacy 1054-1058: not 'finished' yet, return False).
    4. any child not ``"synced"`` -> ``REQUEUE_CHILDREN``
       (legacy 1066-1104). The children are re-enqueued at ``child_rank`` and
       self at ``parent_rank``; legacy lines 1082-1083 define::

           parent_rank = rank - 1
           child_rank  = parent_rank - 1   # == rank - 2

       i.e. children are re-queued at strictly *higher* priority (lower number)
       than the parent so they sync first. Only the non-synced children are
       re-queued (legacy iterates ``finished_children``; an ``active`` child
       blocks too, but in this pure decider any non-synced child uniformly maps
       here). Self is enqueued last, matching legacy order (children loop at
       1092-1094, then self at 1102).
    5. otherwise -> ``PROCEED`` (legacy 1106).

    Args:
        exists: Whether the yml file exists on disk.
        node_status: Lowercase status of this node
            (``"active"``/``"finished"``/``"synced"``), e.g. from
            ``paths.status_of``.
        child_statuses: ``(relpath, status)`` for every child one level down,
            where ``relpath`` is relative to the ``RUNS_*`` root and ``status``
            is the child's lowercase status. Empty for action nodes.
        already_synced: Pre-computed "this yml is already synced" flag (e.g.
            from the ``.prg`` ``s3``/``api`` state); folded into the SKIP gate.
        rank: Current queue priority of this node.

    Returns:
        A :class:`SyncDecision`.
    """
    # 1. legacy 1027-1031
    if not exists:
        return SyncDecision(action=SyncAction.SKIP)

    # 2. legacy 1044-1048
    if already_synced or node_status == "synced":
        return SyncDecision(action=SyncAction.SKIP)

    # 3. legacy 1054-1058
    if node_status == "active":
        return SyncDecision(action=SyncAction.SOFT_BLOCK)

    # 4. legacy 1066-1104 — re-queue unsynced children, then self.
    unsynced = [relpath for relpath, status in child_statuses if status != "synced"]
    if unsynced:
        parent_rank = rank - 1  # legacy 1082
        child_rank = parent_rank - 1  # legacy 1083  (== rank - 2)
        items = [RequeueItem(relpath=rp, rank=child_rank) for rp in unsynced]
        # self denoted by "" so the caller substitutes the node's own path.
        items.append(RequeueItem(relpath="", rank=parent_rank))  # legacy 1102
        return SyncDecision(
            action=SyncAction.REQUEUE_CHILDREN, requeue=tuple(items)
        )

    # 5. legacy 1106
    return SyncDecision(action=SyncAction.PROCEED)


def build_upload_file_list(
    pending: Sequence[str],
    s3_dict: dict,
    hlo_files: Sequence[str],
    misc_files: Sequence[str],
) -> list[str]:
    """Build the de-duplicated pending-upload file list (PURE).

    Mirrors legacy lines 1112-1117::

        prog.dict["files_pending"] += [
            str(p) for p in prog.yml.hlo_files + prog.yml.misc_files
            if str(p) not in prog.dict["files_pending"]
            and str(p) not in prog.dict["files_s3"]
        ]

    i.e. start from the existing ``pending`` list and append each hlo-then-misc
    file (in that order) that is not already pending and not already uploaded
    (a key in ``s3_dict``). The input ``pending`` is not mutated; a new list is
    returned. A file appearing in both ``hlo_files`` and ``misc_files`` is
    appended only once (the second occurrence is already pending after the
    first append).

    Args:
        pending: Existing ``files_pending`` list (relative/abs path strings).
        s3_dict: ``files_s3`` map ``{local_path: s3_key}`` of done uploads.
        hlo_files: Candidate ``.hlo`` file paths.
        misc_files: Candidate non-hlo file paths.

    Returns:
        A new ``pending`` list with the new files appended.
    """
    result = list(pending)
    for p in list(hlo_files) + list(misc_files):
        sp = str(p)
        if sp not in result and sp not in s3_dict:
            result.append(sp)
    return result


def hlo_upload_plan(file_size: int, is_hlo: bool, threshold: int = 1_000_000_000) -> str:
    """Decide whether an hlo file uploads as ``"hlo"`` (json) or ``"parquet"``.

    Mirrors legacy lines 1123-1159. The legacy threshold is ``1024**3`` (1 GiB,
    ``1073741824``); the ``threshold`` default here is the spec's ``1_000_000_000``
    placeholder -- pass ``1024**3`` to match legacy byte-for-byte. The legacy
    comparison is ``fp.stat().st_size < 1GB`` (strictly less than), so a file of
    *exactly* the threshold size converts to parquet.

    Non-hlo files (``is_hlo=False``) take the legacy ``else`` branch (lines
    1160-1165): a plain raw upload, never parquet -- reported here as ``"hlo"``
    (the "upload the file as-is" plan).

    Args:
        file_size: Size of the file in bytes.
        is_hlo: Whether the file has the ``.hlo`` suffix.
        threshold: Size at/above which an hlo converts to parquet.

    Returns:
        ``"hlo"`` or ``"parquet"``.
    """
    if not is_hlo:
        return "hlo"
    # legacy: size < threshold -> hlo (json); else -> parquet
    return "hlo" if file_size < threshold else "parquet"


def patch_metadata(
    meta: dict,
    node_type: str,
    technique_patch: Optional[Callable[[dict, str], dict]] = None,
) -> dict:
    """Patch a yml metadata dict before upload (PURE; returns a NEW dict).

    Mirrors legacy lines 1229-1237:

    1. Rename keys via ``MOD_PATCH`` (line 1230: ``{MOD_PATCH.get(k, k): v ...}``);
       currently only ``exid`` -> ``exec_id``.
    2. Optionally apply ``technique_patch`` -- a caller-injected hook standing in
       for the impure legacy line 1231
       (``MOD_MAP[type](**patched).clean_dict(strip_private=True)``), which
       coerces through the pydantic model. Kept out of the pure domain; the app
       layer injects a callable that performs the model round-trip. ``None``
       skips it.
    3. Technique-name list split (lines 1234-1237): if ``technique_name`` is a
       list, replace it with the element at the ``action_split`` index (default
       ``0``). A scalar ``technique_name`` (or an absent one) is left untouched
       -- note the legacy ``meta.get("technique_name", "NA")`` default only
       feeds the ``isinstance(list)`` test and never writes ``"NA"`` back when
       the value is already a scalar.

    Args:
        meta: The yml metadata dict. **Not mutated.**
        node_type: ``"action"``/``"experiment"``/``"sequence"`` -- passed to
            ``technique_patch`` (the legacy ``MOD_MAP`` key).
        technique_patch: Optional ``(dict, node_type) -> dict`` hook for the
            model-level coercion the pure domain cannot do.

    Returns:
        A new patched dict.
    """
    # 1. legacy 1230 — key rename
    patched = {MOD_PATCH.get(k, k): v for k, v in meta.items()}

    # 2. legacy 1231 — model round-trip, injected (impure) hook
    if technique_patch is not None:
        patched = technique_patch(patched, node_type)

    # 3. legacy 1234-1237 — technique list split
    tech_name = patched.get("technique_name", "NA")
    if isinstance(tech_name, list):
        patched["technique_name"] = tech_name[patched.get("action_split", 0)]

    return patched
