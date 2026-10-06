"""Sequence retire: locate a sequence's run-tree dirs, probe, delete, move.

Reflex-free logic module. Design and contracts:
docs/superpowers/specs/2026-10-06-sequence-retire-page-design.md

This part holds the dataclasses, the anchored line scans, ``locate``,
``in_flight`` and ``ledger_path_for``. Seq ymls can be ~10 MB, so nothing
here parses YAML.
"""

from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

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


def locate(root: str, sequence_uuid: str) -> list[SeqLocation]:
    out = []
    for seq_yml in glob.glob(os.path.join(root, "RUNS*", "*", "*", "*", "*-seq.yml")):
        seq_dir = os.path.dirname(seq_yml)
        run_tree = os.path.relpath(seq_dir, root).split(os.sep)[0]
        if run_tree == SUPERSEDED or not names_uuid(seq_yml, sequence_uuid):
            continue
        meta = top_level(seq_yml, ("sequence_label", "sequence_name", "campaign_name"))
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
