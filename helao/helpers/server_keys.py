"""Well-known server keys.

The data-syncer server is keyed ``SYNC``. It was historically keyed ``DB``,
from when it fronted a SQL database; that database is offline and the code path
that talked to it has been removed, so the key describes what the server
actually does -- shipping run trees to S3.

``DB`` is no longer accepted. It is still recognised for one purpose only: a
config that still carries a ``DB`` server block and no ``SYNC`` block is
rejected loudly by :func:`resolve_sync_server_key`. Silently ignoring it would
disable the syncer (the orchestrator only instantiates ``HelaoSyncer`` when it
finds the key), and unsynced runs are far worse than a refused launch.
"""

__all__ = [
    "SYNC_SERVER_KEY",
    "RETIRED_SYNC_SERVER_KEYS",
    "resolve_sync_server_key",
    "get_sync_server_cfg",
]

from typing import Optional

SYNC_SERVER_KEY = "SYNC"
#: Keys that used to name the syncer. Present in a config, these are an error,
#: not an alias -- see the module docstring.
RETIRED_SYNC_SERVER_KEYS = ("DB",)


def resolve_sync_server_key(
    world_cfg: Optional[dict], preferred: Optional[str] = None
) -> Optional[str]:
    """Return the syncer server key present in ``world_cfg``, or ``None``.

    Prefers ``preferred`` when given, then ``SYNC``. Returns ``None`` when the
    group defines no syncer server, which callers treat as "syncing is not
    configured for this group" (canary and single-server configs rely on this).

    Args:
        world_cfg: Orchestration-group config (the ``servers`` block is read).
        preferred: Explicit server key to check first, for callers that let an
            operator name the syncer server themselves.

    Returns:
        The matching key, or ``None`` if no candidate is present.

    Raises:
        ValueError: The config carries a retired syncer key (``DB``) and no
            ``SYNC`` block, i.e. it was never migrated. Failing here is
            deliberate: returning ``None`` would silently stop syncing runs.
    """
    servers = (world_cfg or {}).get("servers") or {}
    for key in ([preferred] if preferred else []) + [SYNC_SERVER_KEY]:
        if key in servers:
            return key
    retired = [k for k in RETIRED_SYNC_SERVER_KEYS if k in servers]
    if retired:
        raise ValueError(
            f"config defines a retired syncer server key {retired!r} and no "
            f"'{SYNC_SERVER_KEY}' block. Rename the server key to "
            f"'{SYNC_SERVER_KEY}'; the old name is no longer accepted. "
            "Refusing to continue, because ignoring it would leave runs "
            "unsynced with no other symptom."
        )
    return None


def get_sync_server_cfg(
    world_cfg: Optional[dict], preferred: Optional[str] = None
) -> dict:
    """Return the syncer server's config block, or ``{}`` when absent.

    Convenience wrapper over :func:`resolve_sync_server_key` for call sites
    that only want the block and treat a missing syncer as "no config". A
    retired key still raises, as in :func:`resolve_sync_server_key`.
    """
    key = resolve_sync_server_key(world_cfg, preferred=preferred)
    if key is None:
        return {}
    return (world_cfg or {}).get("servers", {}).get(key, {})
