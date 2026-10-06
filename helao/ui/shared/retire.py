"""Sequence retire: locate a sequence's run-tree dirs, probe, delete, move.

Reflex-free logic module. Design and contracts:
docs/superpowers/specs/2026-10-06-sequence-retire-page-design.md

Holds the dataclasses, the anchored line scans, ``locate``, ``in_flight``,
``ledger_path_for``, ``inventory`` and the guarded ``retire``. Seq ymls can be
~10 MB, so nothing here parses YAML.
"""

from __future__ import annotations

import asyncio
import fnmatch
import glob
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx

from helao.helpers import helao_logging as logging
from helao.helpers.run_state import _prg_is_complete

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

Progress = Callable[[str, int, int], Awaitable[None]]  # (phase, done, total)

ENTITY_TYPES = ("EXPERIMENT", "ACTION", "PROCESS", "ANALYSIS")
DELETE_ORDER = ("ANALYSIS", "ACTION", "PROCESS", "EXPERIMENT", "SEQUENCE")
MUST_404 = frozenset({"PROCESS", "ANALYSIS", "SEQUENCE"})
SUPERSEDED = "RUNS_SUPERSEDED"
DELETE_CONCURRENCY = 8
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
    synced: bool  # every location's .prg is complete; False when api_only

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


def is_synced(loc: SeqLocation) -> bool:
    """Whether the location's ``.prg`` sidecar reports the record fully shipped.

    A missing sidecar is unsynced.
    """
    return _prg_is_complete(Path(loc.seq_yml).with_suffix(".prg"))


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


_STATUS = re.compile(r"failed: (\d{3})")


def is_not_found(exc: BaseException) -> bool:
    """404 by status when the message carries one; else by "Could not find"."""
    msg = str(exc)
    if m := _STATUS.search(msg):
        return m.group(1) == "404"
    return "Could not find" in msg


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


_TOKEN = re.compile(r"[0-9A-Za-z][0-9A-Za-z-]*")


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
            if uuids.intersection(_TOKEN.findall(text)):
                hits.append(d)
                break
    return sorted(hits)


async def inventory(
    client: Any, root: str, sequence_uuid: str, progress: Progress
) -> Inventory:
    locations = await asyncio.to_thread(locate, root, sequence_uuid)
    local, n = await asyncio.to_thread(_scan_local, locations)
    synced = bool(locations) and await asyncio.to_thread(
        lambda: all(is_synced(loc) for loc in locations)
    )
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
        synced=synced,
        api_only=nothing_local and (seq_body is not None or any(in_api.values())),
        analysis_dirs=await asyncio.to_thread(
            _analysis_dirs, root, all_procs | in_api["ANALYSIS"]
        ),
    )


_ANCHOR = "; no files were moved"


def _st_dev(path: str) -> int:
    return os.stat(path).st_dev


def _nearest_existing(path: str) -> str:
    while not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def _paths(root: str, loc: SeqLocation, date: str) -> tuple[str, str]:
    src = os.path.join(root, loc.run_tree, *loc.rel_dir.split("/"))
    dst = os.path.join(
        root, SUPERSEDED, f"{date}_retired", loc.run_tree, *loc.rel_dir.split("/")
    )
    return src, dst


def _move_guard(root: str, loc: SeqLocation, src: str, dst: str) -> str:
    """Why this move must be refused, or "" when every guard holds."""
    if not fnmatch.fnmatch(loc.run_tree, "RUNS*") or loc.run_tree == SUPERSEDED:
        return f"run tree {loc.run_tree!r} is not movable"
    cur = os.path.join(root, loc.run_tree)
    for part in loc.rel_dir.split("/"):
        cur = os.path.join(cur, part)
        if os.path.islink(cur):  # rename would move the link, not the data
            return f"{cur} is a symlink"
    tree = os.path.realpath(os.path.join(root, loc.run_tree))
    if not os.path.realpath(src).startswith(tree + os.sep):
        return f"{src} is not strictly inside {tree}"
    if os.path.lexists(dst):
        return f"destination {dst} already exists"
    if _st_dev(src) != _st_dev(_nearest_existing(os.path.dirname(dst))):
        return f"{src} and {dst} are on different devices"
    return ""


def _append(path: str, rec: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")
        f.flush()


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _fail(res: RetireResult, msg: str, st: dict) -> RetireResult:
    """Finish with ok=False; the message says how far the retire got."""
    res.ok = False
    if st["phase"] == "move":
        done = {src for src, _ in res.moved}
        unmoved = [(src, dst) for _, src, dst in st["plan"] if src not in done]
        for src, dst in unmoved:
            if src not in st["move_failed"]:
                try:
                    await asyncio.to_thread(
                        _append,
                        res.ledger_path,
                        {
                            "ts": _stamp(),
                            "entity_type": "DIR",
                            "uuid": src,
                            "outcome": "move_failed",
                            "detail": dst,
                        },
                    )
                except OSError:
                    break
        res.error = (
            f"{msg}; moved: {[s for s, _ in res.moved]}; "
            f"un-moved: {[s for s, _ in unmoved]}; API rows are already deleted"
        )
    elif st["phase"] == "delete":
        res.error = msg + "; API rows may already be deleted" + _ANCHOR
    else:
        res.error = msg + _ANCHOR
    return res


async def retire(
    client: Any,
    root: str,
    inv: Inventory,
    progress: Progress,
    ledger_path: str,
    *,
    allow_unsynced: bool = False,
) -> RetireResult:
    """Guarded, children-first delete of one sequence, then move its run dirs.

    Never raises on failure: every failure is ``ok=False`` with ``error`` set.
    ``asyncio.CancelledError`` is not a failure and propagates unchanged.
    A raising ``progress`` callback is logged and ignored in every phase.
    """
    res = RetireResult(False, ledger_path, {}, {}, {}, [])
    st: dict = {"phase": "pre", "plan": [], "move_failed": set()}
    try:
        return await _retire(
            client, root, inv, progress, ledger_path, res, st, allow_unsynced
        )
    except Exception as exc:  # the contract is "never raises"
        LOGGER.exception("retire: unexpected failure")
        return await _fail(res, f"unexpected error: {exc!r}", st)


async def _retire(
    client: Any,
    root: str,
    inv: Inventory,
    progress: Progress,
    ledger_path: str,
    res: RetireResult,
    st: dict,
    allow_unsynced: bool,
) -> RetireResult:
    stop = False
    errors: list[str] = []
    lock = asyncio.Lock()  # keeps concurrent ledger lines whole and in order

    async def prog(phase: str, done: int, total: int) -> None:
        try:
            await progress(phase, done, total)
        except Exception as exc:
            LOGGER.warning(f"retire: progress callback failed: {exc!r}")

    async def log(entity_type: str, uuid: str, outcome: str, detail: str = "") -> None:
        """Append one ledger line; an OSError sets the stop flag."""
        nonlocal stop
        async with lock:
            try:
                await asyncio.to_thread(
                    _append,
                    ledger_path,
                    {
                        "ts": _stamp(),
                        "entity_type": entity_type,
                        "uuid": uuid,
                        "outcome": outcome,
                        "detail": detail,
                    },
                )
            except OSError as exc:
                stop = True
                errors.append(f"ledger write failed: {exc}")
        if outcome == "move_failed":
            st["move_failed"].add(uuid)

    # 1. ledger first
    n_rows = sum(len(inv.in_api[t]) for t in DELETE_ORDER if t != "SEQUENCE")
    total = n_rows + int(inv.sequence_in_api) + len(inv.locations)

    def sync_flags() -> dict[str, bool]:
        return {
            f"{loc.run_tree}/{loc.rel_dir}": is_synced(loc) for loc in inv.locations
        }

    flags = await asyncio.to_thread(sync_flags)
    try:
        os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
        _append(
            ledger_path,
            {
                "ts": _stamp(),
                "entity_type": "SEQUENCE",
                "uuid": inv.sequence_uuid,
                "outcome": "start",
                "detail": {
                    "api_rows": {t: len(inv.in_api[t]) for t in inv.in_api},
                    "sequence_in_api": inv.sequence_in_api,
                    "locations": len(inv.locations),
                    "allow_unsynced": allow_unsynced,
                    "synced": flags,
                },
            },
        )
    except OSError as exc:
        return await _fail(res, f"cannot write ledger {ledger_path}: {exc}", st)

    # 2. re-verify
    def reverify() -> str:
        for loc in inv.locations:
            if not names_uuid(loc.seq_yml, inv.sequence_uuid):
                return loc.seq_yml
        return ""

    if bad := await asyncio.to_thread(reverify):
        return await _fail(res, f"{bad} no longer names this sequence; re-gather", st)
    if not allow_unsynced:
        now = await asyncio.to_thread(sync_flags)
        if not now or not all(now.values()):
            which = [k for k, v in now.items() if not v] or ["no local location"]
            return await _fail(res, f"not synced: {', '.join(which)}", st)

    # 3. pre-check every move
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    plan = [(loc, *_paths(root, loc, date)) for loc in inv.locations]
    st["plan"] = [(loc, src, dst) for loc, src, dst in plan]

    def precheck() -> str:
        for loc, src, dst in plan:
            if why := _move_guard(root, loc, src, dst):
                return why
        return ""

    if why := await asyncio.to_thread(precheck):
        return await _fail(res, f"move refused: {why}", st)

    # 4. delete, children first
    sem = asyncio.Semaphore(DELETE_CONCURRENCY)
    done = 0
    probe_rows: list[tuple[str, str]] = []  # every row the read-back must probe

    async def delete_one(t: str, uuid: str) -> None:
        nonlocal done, stop
        async with sem:
            if stop:
                return
            st["phase"] = "delete"
            detail = ""
            try:
                await _op(client, "delete_command")(
                    entity_type=t,
                    primary_id=uuid,
                    delete_connected_processes=(t == "SEQUENCE"),
                )
                outcome = "deleted"
            except Exception as exc:
                if is_not_found(exc):
                    outcome = "absent"
                elif t == "SEQUENCE" and is_timeout_or_504(exc):
                    try:
                        gone = not await exists(client, "SEQUENCE", uuid)
                    except Exception as probe_exc:
                        gone, exc = False, probe_exc
                    if gone:
                        outcome, detail = (
                            "deleted",
                            "confirmed absent after timeout/504",
                        )
                    else:
                        outcome, detail = "error", repr(exc)
                else:
                    outcome, detail = "error", repr(exc)
            if outcome == "deleted":
                res.deleted[t] = res.deleted.get(t, 0) + 1
                probe_rows.append((t, uuid))
            elif outcome == "absent":
                res.already_absent[t] = res.already_absent.get(t, 0) + 1
                if t in MUST_404:  # an error without a status can look like a 404
                    probe_rows.append((t, uuid))
            else:
                stop = True
                errors.append(f"delete {t} {uuid} failed: {detail}")
            await log(t, uuid, outcome, detail)
            done += 1
            await prog(f"delete:{t}", done, total)

    for t in DELETE_ORDER:
        rows = sorted(inv.in_api[t]) if t != "SEQUENCE" else []
        if t == "SEQUENCE" and inv.sequence_in_api:
            rows = [inv.sequence_uuid]
        results = await asyncio.gather(
            *(delete_one(t, u) for u in rows), return_exceptions=True
        )
        for r in results:
            if isinstance(r, BaseException):
                LOGGER.warning(f"retire: delete task for {t} raised: {r!r}")
        if stop:
            return await _fail(res, "; ".join(errors), st)

    # 5. read-back
    persisting: dict[str, list[str]] = {}
    failed: list[str] = []

    async def read_back(t: str, uuid: str) -> None:
        async with sem:
            try:
                present = await exists(client, t, uuid)
            except Exception as exc:
                failed.append(f"read-back of {t} {uuid} failed: {exc!r}")
                return
        if not present:
            return
        await log(t, uuid, "persists", "row still readable after delete")
        if t in MUST_404:
            failed.append(f"{t} {uuid} still exists after delete")
        else:
            persisting.setdefault(t, []).append(uuid)

    await asyncio.gather(*(read_back(t, u) for t, u in probe_rows))
    await prog("readback", done, total)
    res.persisting = {t: sorted(v) for t, v in persisting.items()}
    if failed or stop:
        return await _fail(res, "; ".join(failed + errors), st)

    # 6. move
    def move(loc: SeqLocation, src: str, dst: str) -> None:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if why := _move_guard(root, loc, src, dst):
            raise OSError(why)
        os.rename(src, dst)

    st["phase"] = "move"
    for i, (loc, src, dst) in enumerate(plan, 1):
        try:
            await asyncio.to_thread(move, loc, src, dst)
        except OSError as exc:
            await log("DIR", src, "move_failed", dst)
            return await _fail(res, f"move of {src} failed: {exc}", st)
        res.moved.append((src, dst))
        await log("DIR", src, "moved", dst)
        await prog("move", done + i, total)
        if stop:
            return await _fail(res, "; ".join(errors), st)
    res.ok = True
    return res
