"""Guarded lifecycle transitions for HELAO status lists.

3a policy: guards LOG ONLY (never raise, never alter the mutation) so serialized
output is byte-identical to the historical inline list ops. Enforcement is a
later increment (3e) gated on soak telemetry from these warnings.
"""

__all__ = ["guarded_append", "guarded_replace", "guarded_reset"]

import logging
from typing import List, Sequence

from helao.core.models.hlostatus import HloStatus

_LOGGER = logging.getLogger(__name__)  # stdlib on purpose: core/models stays infra-import-free


def _warn_contradiction(status_list: List[HloStatus], owner: str) -> None:
    if HloStatus.active in status_list and HloStatus.finished in status_list:
        _LOGGER.warning("contradictory lifecycle state (active+finished) on %s: %s", owner, status_list)


def guarded_append(status_list: List[HloStatus], new_status: HloStatus, *, owner: str = "?") -> None:
    """Append exactly as legacy inline `.append()` did; warn on duplicate/contradiction."""
    if new_status in status_list:
        _LOGGER.warning("duplicate status append %s on %s: %s", new_status, owner, status_list)
    status_list.append(new_status)          # unconditional — byte-identical to legacy
    _warn_contradiction(status_list, owner)


def guarded_replace(status_list: List[HloStatus], old_status: HloStatus,
                    new_status: HloStatus, *, owner: str = "?") -> None:
    """Exact semantics of Base.replace_status (base.py:997): swap in place, else append."""
    if old_status in status_list:
        status_list[status_list.index(old_status)] = new_status
    else:
        status_list.append(new_status)
    _warn_contradiction(status_list, owner)


def guarded_reset(status_list: List[HloStatus], new_statuses: Sequence[HloStatus], *, owner: str = "?") -> None:
    """Wholesale re-init, in place (equivalent to legacy `x.field = [s]` for all consumers)."""
    status_list[:] = list(new_statuses)
