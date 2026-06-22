"""Command / result value objects returned by pure domain functions.

The domain layer never performs I/O. Pure functions (see
:mod:`helao.framework.domain.lifecycle`) compute the next run-model state plus a
description of the side effects to apply, and return them as immutable value
objects. The caller in ``app/`` realises those effects through the injected
ports.

Purity: this module imports only from ``helao.framework.models`` (and stdlib).
"""

__all__ = ["ActionInit", "SplitResult"]

from dataclasses import dataclass, field
from typing import List
from uuid import UUID

from helao.framework.domain.run_models import RunAction


@dataclass(frozen=True)
class ActionInit:
    """Result of :func:`helao.framework.domain.lifecycle.init_action`.

    Attributes:
        action: The action with identity (timestamp/uuid/status/output_dir)
            assigned. When ``manual`` is true, synthetic sequence/experiment
            identity has also been initialised on it.
        manual: True when the action was auto-promoted to a manual run because
            it had no parent sequence/experiment timestamps.
    """

    action: RunAction
    manual: bool = False


@dataclass(frozen=True)
class SplitResult:
    """Result of :func:`helao.framework.domain.lifecycle.split_action`.

    Attributes:
        new_action: The freshly re-initialised current action (new uuid /
            timestamp / incremented ``action_split``).
        prev_action: A snapshot of the action prior to the split, marked
            ``HloStatus.split`` and linked to ``new_action`` as its child.
        open_file_conns: File-connection keys to open (header write) for the new
            action — one per prior file connection. Already mirrored onto
            ``new_action.file_conn_keys``.
        close_file_conns: File-connection keys to close on the previous action —
            the prior action's ``file_conn_keys``.
    """

    new_action: RunAction
    prev_action: RunAction
    open_file_conns: List[UUID] = field(default_factory=list)
    close_file_conns: List[UUID] = field(default_factory=list)
