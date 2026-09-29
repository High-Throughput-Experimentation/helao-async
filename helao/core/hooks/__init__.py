"""One contract for everything that runs around a record's ``finished`` transition.

Two phases (spec D1). **Pre-finish** runs inside the server that owns the
record -- the action server for an action, the orchestrator or ``MicroOrch``
for an experiment or sequence -- in config order, before the final yml is
written and before ``finished`` is emitted; it may change the record.
**Post-finish** runs in SYNC after the record is finished and may not change
it. Both phases use :class:`FinishHook`; the existing ``HloPostProcessor`` /
``MetaProcessor`` classes run unchanged through the adapters in
:mod:`helao.core.hooks.loader`.
"""

__all__ = [
    "FinishHook",
    "HookConfigError",
    "HookMap",
    "HookSet",
    "LEVELS",
    "PostfinishContext",
    "PrefinishContext",
]

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

#: Record levels a hook can be configured at; also the only keys
#: ``postfinish_hooks`` may have (spec §3.3).
LEVELS = ("action", "experiment", "sequence")

#: Normalized hook config: hook name -> {record name or "*": args or None}.
#: Dict order is execution order (spec D3).
HookMap = dict[str, dict[str, Optional[dict]]]


class HookConfigError(ValueError):
    """A hook config that must not degrade silently to "no hooks" (spec §3.3)."""


class FinishHook(ABC):
    """A unit of finish-time work (spec §4.1).

    ``blocking`` is consulted for post-finish only (spec D5): a blocking
    failure stops the chain and keeps the record unsynced; a non-blocking one
    is recorded and the chain continues. ``phase``/``levels`` let the loader
    refuse a hook configured where it cannot run (``None`` = anywhere). A hook
    that does blocking I/O or CPU work wraps it in ``asyncio.to_thread``
    itself. One instance per server, created at startup and reused.
    """

    blocking: bool = True
    phase: Optional[str] = None  # "prefinish" | "postfinish" | None
    levels: Optional[tuple[str, ...]] = None  # subset of LEVELS, or None

    @abstractmethod
    async def run(self, ctx) -> None:
        """Raise to signal failure."""


@dataclass
class PrefinishContext:
    record: Any  # Action | Experiment | Sequence -- live model, hooks may mutate
    record_dir: Path
    server: Any  # ActionHost / Base / Orch / MicroOrch
    args: Optional[dict]


@dataclass
class PostfinishContext:
    yml: Any  # HelaoYml of the finished record
    prg: Any  # Progress -- read-only for the hook; the runner owns prg.dict["hooks"]
    syncer: Any  # the SyncDriver: S3 client, world config, sync_process, ...
    args: Optional[dict]
    #: ``sync_yml`` call options handed through to the built-ins (settled
    #: decision A3): force_s3, force_api, compress, retries.
    opts: dict = field(default_factory=dict)

    @property
    def data(self):
        """``HelaoData`` over the finished record, built on first access (A7)."""
        from helao.helpers.helao_data import HelaoData

        return HelaoData(str(self.yml.target))


@dataclass
class HookSet:
    """Normalized config plus the loaded instances it names, for one level."""

    cfg: HookMap
    hooks: dict[str, FinishHook]

    @classmethod
    def empty(cls) -> "HookSet":
        return cls(cfg={}, hooks={})

    def select(self, name: str) -> list[tuple[str, FinishHook, Optional[dict]]]:
        """Hooks that apply to record ``name``, in config order (spec §5 step 1).

        An exact entry wins over ``"*"`` for the args; ``"*"`` matches every
        record.
        """
        out = []
        for hook_name, targets in self.cfg.items():
            if name in targets:
                out.append((hook_name, self.hooks[hook_name], targets[name]))
            elif "*" in targets:
                out.append((hook_name, self.hooks[hook_name], targets["*"]))
        return out
