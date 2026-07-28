"""Well-known server keys and their legacy aliases.

The data-syncer server is keyed ``SYNC``. It was historically keyed ``DB``,
from when it fronted a SQL database via ``SyncDriver.to_api()``; that path is
a no-op stub and the database is offline, so the key was renamed to describe
what the server actually does -- shipping run trees to S3.

``DB`` is still accepted as a deprecated alias so a config that has not been
migrated keeps syncing instead of silently disabling the syncer (the
orchestrator only instantiates ``HelaoSyncer`` when it finds the key). The
alias is scheduled for removal; :func:`resolve_sync_server_key` warns once per
process per key when it is used.
"""

__all__ = [
    "SYNC_SERVER_KEY",
    "LEGACY_SYNC_SERVER_KEYS",
    "resolve_sync_server_key",
    "get_sync_server_cfg",
]

from typing import Optional

from helao.helpers import helao_logging as logging

SYNC_SERVER_KEY = "SYNC"
LEGACY_SYNC_SERVER_KEYS = ("DB",)

# keys already warned about, so a per-action call site does not spam the log
_WARNED: set = set()


def _logger():
    return (
        logging.LOGGER if logging.LOGGER is not None else logging.make_logger(__file__)
    )


def resolve_sync_server_key(
    world_cfg: Optional[dict], preferred: Optional[str] = None
) -> Optional[str]:
    """Return the syncer server key present in ``world_cfg``, or ``None``.

    Prefers ``preferred`` when given, then ``SYNC``, then each legacy alias.
    Returns ``None`` when the group defines no syncer server, which callers
    treat as "syncing is not configured for this group".

    Args:
        world_cfg: Orchestration-group config (the ``servers`` block is read).
        preferred: Explicit server key to check first, for callers that let an
            operator name the syncer server themselves.

    Returns:
        The matching key, or ``None`` if no candidate is present.
    """
    servers = (world_cfg or {}).get("servers") or {}
    candidates = ([preferred] if preferred else []) + [SYNC_SERVER_KEY]
    candidates += list(LEGACY_SYNC_SERVER_KEYS)
    for key in candidates:
        if key in servers:
            if key in LEGACY_SYNC_SERVER_KEYS and key not in _WARNED:
                _WARNED.add(key)
                _logger().warning(
                    f"config uses the legacy '{key}' server key for the data "
                    f"syncer; rename it to '{SYNC_SERVER_KEY}'. The '{key}' "
                    "alias will be removed in a future release."
                )
            return key
    return None


def get_sync_server_cfg(
    world_cfg: Optional[dict], preferred: Optional[str] = None
) -> dict:
    """Return the syncer server's config block, or ``{}`` when absent.

    Convenience wrapper over :func:`resolve_sync_server_key` for call sites
    that only want the block and treat a missing syncer as "no config".
    """
    key = resolve_sync_server_key(world_cfg, preferred=preferred)
    if key is None:
        return {}
    return (world_cfg or {}).get("servers", {}).get(key, {})
