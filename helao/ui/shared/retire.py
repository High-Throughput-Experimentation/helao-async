"""Sequence retire: locate a sequence's run-tree dirs, probe, delete, move.

Reflex-free logic module. Design and contracts:
docs/superpowers/specs/2026-10-06-sequence-retire-page-design.md

This part holds the dataclasses, the anchored line scans, ``locate``,
``in_flight`` and ``ledger_path_for``. Seq ymls can be ~10 MB, so nothing
here parses YAML.
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

Progress = Callable[[str, int, int], Awaitable[None]]  # (phase, done, total)

ENTITY_TYPES = ("EXPERIMENT", "ACTION", "PROCESS", "ANALYSIS")
DELETE_ORDER = ("ANALYSIS", "ACTION", "PROCESS", "EXPERIMENT", "SEQUENCE")
MUST_404 = frozenset({"PROCESS", "ANALYSIS", "SEQUENCE"})
SUPERSEDED = "RUNS_SUPERSEDED"
_NULLS = {"", "null", "None", "~"}


@dataclass(frozen=True)
class SeqLocation:
    run_tree: str  # "RUNS", "RUNS_SYNCED", "RUNS_FINISHED", ...
    rel_dir: str  # output dir relative to <root>/<run_tree>
    seq_yml: str  # absolute path of the *-seq.yml
    label: str  # sequence_label ("" if absent)
    name: str  # sequence_name
    campaign: str  # campaign_name


@dataclass
class Inventory:
    sequence_uuid: str
    locations: list[SeqLocation]
    local: dict[str, set[str]]  # {"EXPERIMENT"|"ACTION"|"PROCESS"|"ANALYSIS": uuids}
    in_api: dict[str, set[str]]  # subset of the union that read back 200
    sequence_in_api: bool
    sequence_label: str
    campaign_name: str
    api_only: bool  # not found locally, present in API
    analysis_dirs: list[str]  # local ANALYSES/ dirs referencing these processes

    @property
    def nothing_to_retire(self) -> bool:
        return (
            not self.locations
            and not self.sequence_in_api
            and not any(self.in_api.values())
        )


@dataclass
class RetireResult:
    ok: bool
    ledger_path: str
    deleted: dict[str, int]
    already_absent: dict[str, int]
    persisting: dict[
        str, list[str]
    ]  # EXPERIMENT/ACTION rows acknowledged, still readable
    moved: list[tuple[str, str]]  # (src, dst)
    error: str = ""


def top_level(path: str, keys: tuple[str, ...]) -> dict[str, str]:
    """First unindented ``key: value`` line per key; stops once all are seen.

    Values are stripped; null-like values are dropped from the result.
    """
    found: dict[str, str] = {}
    want = set(keys)
    with open(path, errors="replace") as f:
        for line in f:
            if not line or line[0] in " \t":
                continue
            key, sep, val = line.partition(":")
            if sep and key in want and key not in found:
                found[key] = val.strip()
                if len(found) == len(want):
                    break
    return {k: v for k, v in found.items() if v not in _NULLS}


def names_uuid(seq_yml: str, sequence_uuid: str) -> bool:
    try:
        return (
            top_level(seq_yml, ("sequence_uuid",)).get("sequence_uuid") == sequence_uuid
        )
    except OSError:
        return False


_SEQ_KEYS = ("sequence_uuid", "sequence_label", "sequence_name", "campaign_name")


def locate(root: str, sequence_uuid: str) -> list[SeqLocation]:
    out = []
    for seq_yml in glob.glob(os.path.join(root, "RUNS*", "*", "*", "*", "*-seq.yml")):
        seq_dir = os.path.dirname(seq_yml)
        run_tree = os.path.relpath(seq_dir, root).split(os.sep)[0]
        if run_tree == SUPERSEDED:
            continue
        try:
            meta = top_level(seq_yml, _SEQ_KEYS)
        except OSError:
            continue
        if meta.get("sequence_uuid") != sequence_uuid:
            continue
        out.append(
            SeqLocation(
                run_tree=run_tree,
                rel_dir=os.path.relpath(seq_dir, os.path.join(root, run_tree)).replace(
                    os.sep, "/"
                ),
                seq_yml=seq_yml,
                label=meta.get("sequence_label", ""),
                name=meta.get("sequence_name", ""),
                campaign=meta.get("campaign_name", ""),
            )
        )
    return sorted(out, key=lambda loc: (loc.run_tree, loc.rel_dir))


def in_flight(sources_root: str, sequence_uuid: str, rel_dirs: list[str]) -> str | None:
    """Path of the first processing state file that claims this sequence, else None."""
    for path in sorted(
        glob.glob(os.path.join(sources_root, "*", "processing", "*.state.json"))
    ):
        try:
            with open(path) as f:
                state = json.load(f)
            if not isinstance(state, dict):
                raise ValueError("not a dict")
        except (OSError, ValueError) as exc:
            LOGGER.warning(f"retire: skipping unreadable state file {path}: {exc}")
            continue
        out_dir = state.get("sequence_output_dir")
        if state.get("sequence_uuid") == sequence_uuid or (
            isinstance(out_dir, str)
            and out_dir.replace("\\", "/").strip("/") in rel_dirs
        ):
            return path
    return None


def ledger_path_for(root: str, sequence_uuid: str, now: datetime) -> str:
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return os.path.join(root, "STATES", f"retire_{sequence_uuid}_{stamp}.jsonl")


READ_OPS: dict[str, tuple[str, str]] = {
    "SEQUENCE": ("read_sequence", "sequence_uuid"),
    "EXPERIMENT": ("read_experiment", "experiment_uuid"),
    "ACTION": ("read_action", "action_uuid"),
    "PROCESS": ("read_process", "process_uuid"),
    "ANALYSIS": ("read_analysis", "analysis_uuid"),
}


def is_not_found(exc: BaseException) -> bool:
    msg = str(exc)
    return "failed: 404" in msg or "Could not find" in msg


def is_timeout_or_504(exc: BaseException) -> bool:
    if "failed: 504" in str(exc):
        return True
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        if isinstance(cur, httpx.TimeoutException):
            return True
        seen.add(id(cur))
        cur = cur.__cause__ or cur.__context__
    return False


def _op(client: Any, name: str) -> Callable[..., Awaitable[Any]]:
    fn = getattr(client, name, None)
    if fn is None:
        raise RuntimeError(f"metadata client has no operation {name!r}")
    return fn


async def _read(client: Any, entity_type: str, uuid: str) -> Any:
    """Body of the entity's row, or None on 404; other failures raise RuntimeError."""
    name, kwarg = READ_OPS[entity_type]
    fn = _op(client, name)
    try:
        return await fn(**{kwarg: uuid})
    except Exception as exc:
        if is_not_found(exc):
            return None
        raise RuntimeError(f"probe of {entity_type} {uuid} failed: {exc!r}") from exc


async def exists(client: Any, entity_type: str, uuid: str) -> bool:
    return await _read(client, entity_type, uuid) is not None


async def _list_or_empty(client: Any, op: str, **kw: str) -> Any:
    try:
        return await _op(client, op)(**kw)
    except RuntimeError as exc:
        if is_not_found(exc):
            return []
        raise


def _scan_local(locations: list[SeqLocation]) -> tuple[dict[str, set[str]], int]:
    local: dict[str, set[str]] = {t: set() for t in ENTITY_TYPES}
    files = 0
    for loc in locations:
        seq_dir = os.path.dirname(loc.seq_yml)
        for yml in glob.glob(os.path.join(seq_dir, "*", "*-exp.yml")):
            files += 1
            if u := top_level(yml, ("experiment_uuid",)).get("experiment_uuid"):
                local["EXPERIMENT"].add(u)
        for yml in glob.glob(os.path.join(seq_dir, "*", "*", "*-act.yml")):
            files += 1
            found = top_level(yml, ("action_uuid", "process_uuid"))
            if "action_uuid" in found:
                local["ACTION"].add(found["action_uuid"])
            if "process_uuid" in found:
                local["PROCESS"].add(found["process_uuid"])
    return local, files


def _analysis_dirs(root: str, uuids: set[str]) -> list[str]:
    hits = []
    for d in glob.glob(os.path.join(root, "ANALYSES", "*", "*", "*")):
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            path = os.path.join(d, name)
            if not name.endswith(".yml") or not os.path.isfile(path):
                continue
            try:
                with open(path, errors="replace") as f:
                    text = f.read()
            except OSError as exc:
                LOGGER.warning(
                    f"retire: skipping unreadable analysis file {path}: {exc}"
                )
                continue
            if any(u in text for u in uuids):
                hits.append(d)
                break
    return sorted(hits)


async def inventory(
    client: Any, root: str, sequence_uuid: str, progress: Progress
) -> Inventory:
    locations = await asyncio.to_thread(locate, root, sequence_uuid)
    local, n = await asyncio.to_thread(_scan_local, locations)
    await progress("scan", n, n)

    seq_body = await _read(client, "SEQUENCE", sequence_uuid)
    listed = await _list_or_empty(
        client, "read_processes_by_sequence", sequence_uuid=sequence_uuid
    )
    if not isinstance(listed, list):
        raise RuntimeError(
            f"read_processes_by_sequence returned {type(listed).__name__}; "
            "expected a list"
        )
    api_procs = {u for p in listed if (u := p.get("process_uuid"))}
    all_procs = local["PROCESS"] | api_procs

    in_api: dict[str, set[str]] = {t: set() for t in ENTITY_TYPES}
    in_api["PROCESS"] = set(api_procs)
    sem = asyncio.Semaphore(8)
    total = (
        len(local["EXPERIMENT"])
        + len(local["ACTION"])
        + len(local["PROCESS"])
        + len(all_procs)
    )
    done = 0

    async def tick() -> None:
        nonlocal done
        done += 1
        await progress("probe", done, total)

    async def probe(entity_type: str, uuid: str) -> None:
        async with sem:
            if await exists(client, entity_type, uuid):
                in_api[entity_type].add(uuid)
        await tick()

    async def analyses(proc: str) -> None:
        async with sem:
            rows = await _list_or_empty(
                client, "read_analysis_by_process", process_uuid=proc
            )
        in_api["ANALYSIS"].update(u for a in rows if (u := a.get("analysis_uuid")))
        await tick()

    tasks = [
        asyncio.ensure_future(c)
        for c in (
            *(
                probe(t, u)
                for t in ("EXPERIMENT", "ACTION", "PROCESS")
                for u in local[t]
            ),
            *(analyses(p) for p in all_procs),
        )
    ]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    if locations:
        label, campaign = locations[0].label, locations[0].campaign
    else:
        body = seq_body if isinstance(seq_body, dict) else {}
        label = body.get("sequence_label", "")
        campaign = body.get("campaign_name", "")
    nothing_local = not locations
    return Inventory(
        sequence_uuid=sequence_uuid,
        locations=locations,
        local=local,
        in_api=in_api,
        sequence_in_api=seq_body is not None,
        sequence_label=label,
        campaign_name=campaign,
        api_only=nothing_local and (seq_body is not None or any(in_api.values())),
        analysis_dirs=await asyncio.to_thread(
            _analysis_dirs, root, all_procs | in_api["ANALYSIS"]
        ),
    )
