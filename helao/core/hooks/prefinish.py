"""Pre-finish runner (spec §5): run the matching hooks, record failures, never raise."""

__all__ = ["run_prefinish"]

from datetime import datetime
from pathlib import Path

from helao.core.hooks import HookSet, PrefinishContext
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


async def run_prefinish(
    hook_set: HookSet, record, name: str, record_dir, server
) -> None:
    """Run every hook in ``hook_set`` that applies to ``name``, in config order.

    A raising hook is alerted with its name, the record name and uuid, appended
    to ``record.prefinish_errors`` as ``{"hook", "error", "ts"}``, and the
    next hook still runs (D6). The caller then writes the final yml and emits
    ``finished``. No timeout (spec §5).
    """
    kind = record.__class__.__name__.lower()
    uuid = getattr(record, f"{kind}_uuid", None)
    for hook_name, hook, args in hook_set.select(name):
        LOGGER.info(f"Running pre-finish hook {hook_name!r} for {kind} {name}")
        try:
            await hook.run(
                PrefinishContext(
                    record=record, record_dir=Path(record_dir), server=server, args=args
                )
            )
        except Exception as exc:
            LOGGER.error(
                f"pre-finish hook {hook_name!r} failed for {kind} {name} ({uuid})",
                exc_info=True,
            )
            LOGGER.alert(  # type: ignore[attr-defined]
                f"pre-finish hook {hook_name!r} failed for {kind} {name} ({uuid}): "
                f"{type(exc).__name__}: {exc}"
            )
            record.prefinish_errors.append(
                {
                    "hook": hook_name,
                    "error": f"{type(exc).__name__}: {exc}",
                    "ts": datetime.now().isoformat(timespec="seconds"),
                }
            )
