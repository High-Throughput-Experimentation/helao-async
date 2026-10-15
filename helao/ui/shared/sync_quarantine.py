"""Sync quarantine page logic: list, release and write off parked records.

Reflex-free. Design and contracts:
docs/superpowers/specs/2026-10-15-sync-write-off-design.md (section 4.6).

Every call to the syncer returns a value that separates "unknown" (``None``)
from a real answer: a transport failure is never reported as success or refusal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from helao.core.error import ErrorCodes
from helao.helpers import helao_logging as logging
from helao.helpers.dispatcher import async_private_dispatcher
from helao.helpers.server_keys import resolve_sync_server_key

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

CALL_TIMEOUT = 10
ERROR_CHARS = 200
UNKNOWN = "sent, outcome unknown — refresh"


def sync_target(world_cfg: Optional[dict]) -> Optional[tuple[str, str, int]]:
    """``(key, host, port)`` of the syncer, or ``None`` when there is none."""
    try:
        key = resolve_sync_server_key(world_cfg)
    except ValueError:
        return None
    if key is None:
        return None
    cfg = ((world_cfg or {}).get("servers") or {}).get(key) or {}
    host, port = cfg.get("host"), cfg.get("port")
    if not host or port is None:
        return None
    return key, str(host), int(port)


async def _call(target, action: str, params: dict):
    """``(body, True)`` on a clean reply; ``(None, False)`` on any transport failure."""
    key, host, port = target
    try:
        body, code = await async_private_dispatcher(
            server_key=key,
            host=host,
            port=port,
            private_action=action,
            params_dict=params,
            timeout=CALL_TIMEOUT,
            retries=1,  # the default of 5 would replay a mutating call
        )
    except Exception:
        LOGGER.error(f"'{key}' {action} failed", exc_info=True)
        return None, False
    if code != ErrorCodes.none:
        return None, False  # an HTTP error body is not an answer
    return body, True


async def fetch(target) -> Optional[list[dict]]:
    """Quarantined entries from ``/tasks``; ``None`` means unknown, never empty."""
    body, ok = await _call(target, "tasks", {})
    if not ok or not isinstance(body, dict):
        return None
    entries = body.get("quarantined")
    return entries if isinstance(entries, list) else None


def incomplete(entry: dict) -> bool:
    """Whether the entry may be an incomplete-process-group park."""
    return entry.get("kind") == "experiment" and entry.get("immediate") is True


def rows(entries: list[dict]) -> list[list[str]]:
    """Table rows: yml, dir name, cause, quarantined_at, strikes, last_error, flag."""
    return [
        [
            str(e.get("yml") or ""),
            Path(str(e.get("path") or "")).name,
            "incomplete process group" if incomplete(e) else "parked — see last error",
            str(e.get("quarantined_at") or ""),
            str(e.get("strikes", "")),
            str(e.get("last_error") or "")[:ERROR_CHARS],
            "1" if incomplete(e) else "",
        ]
        for e in entries
    ]


def is_armed(dir_name: str, confirm: str, reason: str, operator: str) -> bool:
    return (
        bool(dir_name)
        and confirm.strip() == dir_name
        and bool(reason.strip())
        and bool(operator.strip())
    )


def _describe(body: dict) -> tuple[Optional[bool], str]:
    if body.get("ok") is False:
        return False, str(body.get("error") or "refused")
    status = body.get("status")
    if body.get("ok") is not True or not status:
        return None, UNKNOWN
    if status == "requeued":
        msg = (
            f"already written off at {body.get('at')} by {body.get('operator')}; "
            "re-queued"
        )
    elif status == "written off" and body.get("groups"):
        keys = list(body["groups"])  # int over RPC, str over HTTP
        try:
            keys.sort(key=int)
        except (TypeError, ValueError):
            keys.sort(key=str)
        msg = f"written off (process groups {', '.join(str(g) for g in keys)})"
    else:
        msg = str(status)
    if body.get("warning"):
        msg += f"; WARNING: {body['warning']}"
    return True, msg


async def release(target, yml: str) -> tuple[Optional[bool], str]:
    """Release a record via ``/finish_yml``, which echoes the path on success."""
    body, ok = await _call(target, "finish_yml", {"yml_path": yml})
    if not ok or body != yml:
        return None, UNKNOWN
    return True, "released; re-queued"


async def write_off(
    target, yml: str, reason: str, operator: str
) -> tuple[Optional[bool], str]:
    body, ok = await _call(
        target,
        "write_off",
        {"yml_path": yml, "reason": reason, "operator": operator},
    )
    if not ok or not isinstance(body, dict):
        return None, UNKNOWN
    return _describe(body)
